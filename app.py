# app.py
import streamlit as st
import uuid
import datetime
import extra_streamlit_components as stx
from models import (Institution, User, Category, Tracking, Item, Post, load_database,
                    save_to_supabase, update_status_in_supabase, authenticate_user, restore_session)

st.set_page_config(page_title="FoundIt - Campus Lost & Found", page_icon="", layout="centered")

COOKIE_NAME = "foundit_refresh_token"
COOKIE_DAYS = 7
CLAIMED_RETENTION_DAYS = 7
CAMPUS_LOCATIONS = ["RSY Building", "RG Birrey"]

cookie_manager = stx.CookieManager()

school = Institution("Mapúa Malayan Colleges Mindanao", "Davao City")


def days_left(date_claimed):
    """Days remaining before a claimed item is purged, or None if unknown."""
    try:
        claimed_at = datetime.datetime.fromisoformat(date_claimed)
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=datetime.timezone.utc)
        expires_at = claimed_at + datetime.timedelta(days=CLAIMED_RETENTION_DAYS)
        remaining = expires_at - datetime.datetime.now(datetime.timezone.utc)
        return max(remaining.days, 0)
    except (TypeError, ValueError):
        return None


if "categories" not in st.session_state:
    st.session_state.categories = [
        Category("Electronics", "CAT-01"),
        Category("Tumblers/Bottles", "CAT-02"),
        Category("IDs/Cards", "CAT-03"),
        Category("Others", "CAT-04")
    ]

if "posts" not in st.session_state:
    st.session_state.posts = load_database(st.session_state.categories)

if "current_user" not in st.session_state:
    st.session_state.current_user = None

if "logged_out" not in st.session_state:
    st.session_state.logged_out = False

if "pending_token" not in st.session_state:
    st.session_state.pending_token = None

if "pending_delete" not in st.session_state:
    st.session_state.pending_delete = False

if "status_msg" not in st.session_state:
    st.session_state.status_msg = None

# --- AUTO-LOGIN FROM COOKIE (survives page refresh) ---
if not st.session_state.current_user and not st.session_state.logged_out:
    saved_token = cookie_manager.get(COOKIE_NAME)
    if saved_token:
        restored = restore_session(saved_token)
        if restored and "error" not in restored:
            st.session_state.current_user = User(
                username=restored["email"].split("@")[0],
                institutional_id=restored["email"],
                is_admin=restored["is_admin"],
            )
            st.session_state.pending_token = restored["refresh_token"]
            st.rerun()

# --- WRITE / CLEAR THE COOKIE SAFELY ---
if st.session_state.pending_token and st.session_state.current_user:
    cookie_manager.set(
        COOKIE_NAME,
        st.session_state.pending_token,
        expires_at=datetime.datetime.now() + datetime.timedelta(days=COOKIE_DAYS),
    )
    st.session_state.pending_token = None

if st.session_state.pending_delete and not st.session_state.current_user:
    cookie_manager.delete(COOKIE_NAME)
    st.session_state.pending_delete = False

st.title("FoundIt: Campus Lost & Found Hub")
st.caption(f"{school.get_details()}")
st.markdown("---")

# --- AUTHENTICATION ---
if not st.session_state.current_user:
    st.subheader("Login")
    with st.form("login_form"):
        email = st.text_input("Institutional Email")
        password = st.text_input("Password", type="password")
        submit_login = st.form_submit_button("Login")

        if submit_login:
            auth_result = authenticate_user(email, password)
            if auth_result["success"]:
                logged_user = User(username=email.split("@")[0], institutional_id=email, is_admin=auth_result["is_admin"])
                st.session_state.current_user = logged_user
                st.session_state.logged_out = False
                st.session_state.pending_token = auth_result["refresh_token"]
                st.rerun()
            else:
                st.error(f"Authentication failed: {auth_result['error']}")
else:
    st.sidebar.write(f"**{st.session_state.current_user.username}**")
    st.sidebar.caption(f"Role: {'Administrator' if st.session_state.current_user.is_admin else 'Student/Faculty'}")

    if st.sidebar.button("Logout"):
        st.session_state.current_user = None
        st.session_state.logged_out = True
        st.session_state.pending_delete = True
        st.rerun()

    st.sidebar.markdown("---")

    # Role-based navigation setup
    if st.session_state.current_user.is_admin:
        navigation = st.sidebar.radio(
            "Navigation",
            ["View Feed", "Claimed Items", "Report Item", "Update Tracking Status"]
        )
    else:
        navigation = st.sidebar.radio("Navigation", ["View Feed", "Claimed Items"])
        st.sidebar.info("You are logged in as a standard user. Only authorized administrators can report or update items.")

    # --- 1. VIEW FEED (active items only) ---
    if navigation == "View Feed":
        st.header("Recent Dashboard Feed")

        col_search, col_campus = st.columns([2, 1])
        with col_search:
            search_query = st.text_input("Search feed (title, category, description):", "").strip().lower()
        with col_campus:
            campus_filter = st.selectbox("Campus", ["All Campuses"] + CAMPUS_LOCATIONS, key="feed_campus")

        posts_to_display = [
            p for p in st.session_state.posts[::-1]
            if p.item.tracking.current_status != "Claimed"
        ]

        if campus_filter != "All Campuses":
            posts_to_display = [
                p for p in posts_to_display
                if p.item.campus_location == campus_filter
            ]

        if search_query:
            posts_to_display = [
                p for p in posts_to_display
                if search_query in p.item.item_name.lower() or
                   search_query in p.item.category.category_name.lower() or
                   search_query in (p.item.description or "").lower()
            ]

        if not posts_to_display:
            st.info("No items match your search or filter.")
        else:
            for post in posts_to_display:
                with st.container():
                    st.subheader(f"{post.item.item_name}")
                    if post.item.image_url:
                        st.image(post.item.image_url, width=300)
                    st.write(f"**Status:** `{post.item.tracking.current_status}`")
                    st.write(f"**Campus Location:** `{post.item.campus_location}`")
                    st.write(f"**Category:** {post.item.category.category_name}")
                    st.write(f"**Description:** {post.item.description}")
                    st.caption(f"Posted by {post.user.username} on {post.date_posted}")
                    st.markdown("---")

    # --- 2. CLAIMED ITEMS (kept for 7 days, then auto-purged) ---
    elif navigation == "Claimed Items":
        st.header("Claimed Items")
        st.caption(f"Claimed items stay here for {CLAIMED_RETENTION_DAYS} days, then are removed automatically.")
        claimed_campus = st.selectbox("Campus", ["All Campuses"] + CAMPUS_LOCATIONS, key="claimed_campus")

        claimed_posts = [
            p for p in st.session_state.posts[::-1]
            if p.item.tracking.current_status == "Claimed"
        ]
        if claimed_campus != "All Campuses":
            claimed_posts = [p for p in claimed_posts if p.item.campus_location == claimed_campus]

        if not claimed_posts:
            st.info("No claimed items.")
        else:
            for post in claimed_posts:
                st.subheader(post.item.item_name)
                if post.item.image_url:
                    st.image(post.item.image_url, width=300)
                st.write(f"**Campus Location:** `{post.item.campus_location}`")
                st.write(f"**Category:** {post.item.category.category_name}")
                remaining = days_left(post.item.tracking.date_claimed)
                if remaining is not None:
                    st.caption(f"Removed in {remaining} day(s)")
                st.markdown("---")

    # --- 3. REPORT ITEM (Admin Only) ---
    elif navigation == "Report Item":
        st.header("Report a Lost Item")
        with st.form("report_form"):
            item_name = st.text_input("Item Name")
            description = st.text_area("Description / Distinguishing Features")
            campus_location = st.selectbox("Campus Holding Office", CAMPUS_LOCATIONS)

            cat_names = [cat.category_name for cat in st.session_state.categories]
            selected_cat_name = st.selectbox("Category", cat_names)

            uploaded_image = st.file_uploader("Upload Item Photo", type=["jpg", "jpeg", "png"])

            submit_post = st.form_submit_button("Post Item")

            if submit_post:
                if item_name.strip():
                    selected_cat = next(cat for cat in st.session_state.categories if cat.category_name == selected_cat_name)
                    new_item = Item(item_name, description, selected_cat, campus_location=campus_location)
                    today_date = datetime.date.today().strftime("%Y-%m-%d")
                    new_post = Post(f"POST-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:6]}", today_date, st.session_state.current_user, new_item)

                    save_to_supabase(new_post, image_file=uploaded_image)
                    st.session_state.posts = load_database(st.session_state.categories)
                    st.success("Item posted successfully and saved to Supabase!")
                else:
                    st.warning("Please provide an item name.")

    # --- 4. UPDATE TRACKING STATUS (Admin Only) ---
    elif navigation == "Update Tracking Status":
        st.header("Update Item Status")

        # Show the message saved before the rerun, then clear it
        if st.session_state.status_msg:
            st.success(st.session_state.status_msg)
            st.session_state.status_msg = None

        if not st.session_state.posts:
            st.info("No items available to update.")
        else:
            post_options = {p.post_id: p for p in st.session_state.posts}
            selected_id = st.selectbox(
                "Select Item to Update",
                list(post_options.keys()),
                format_func=lambda pid: f"{post_options[pid].item.item_name} ({post_options[pid].item.tracking.current_status}) - {post_options[pid].user.username}",
            )
            target_post = post_options[selected_id]
            new_status = st.radio("Select New Status", ["Lost", "Pending Claim", "Claimed"])

            if st.button("Apply Status Update"):
                target_post.item.tracking.update_tracking_status(new_status)
                update_status_in_supabase(target_post.post_id, new_status)
                st.session_state.posts = load_database(st.session_state.categories)
                st.session_state.status_msg = f"Status updated to **{new_status}** in Supabase!"
                st.rerun()
