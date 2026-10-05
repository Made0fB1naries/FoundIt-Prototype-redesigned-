# app.py
import html
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
STATUS_CLASS = {"Lost": "fi-lost", "Pending Claim": "fi-pending", "Claimed": "fi-claimed"}

THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
html, body, .stApp, button, input, textarea, label, p, h1, h2, h3 { font-family: 'Roboto', sans-serif; }
.stApp { background: #000000; }
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.5rem; max-width: 1040px; }
footer { visibility: hidden; }
.fi-brand { display: flex; align-items: center; gap: 12px; }
.fi-logo { width: 44px; height: 44px; border-radius: 14px; background: #A8C7FA; color: #062E6F; font-weight: 700; font-size: 1.4rem; display: flex; align-items: center; justify-content: center; }
.fi-name { font-size: 1.4rem; font-weight: 700; line-height: 1.1; }
.fi-sub { color: #80868B; font-size: 0.8rem; }
.fi-user { display: flex; align-items: center; gap: 10px; justify-content: flex-end; }
.fi-avatar { width: 36px; height: 36px; border-radius: 50%; background: #1E2A3A; color: #D3E3FD; display: flex; align-items: center; justify-content: center; font-weight: 500; }
.fi-uname { font-weight: 500; font-size: 0.9rem; line-height: 1.1; }
.fi-role { color: #80868B; font-size: 0.75rem; }
.fi-welcome { text-align: center; margin: 2rem 0 1rem; }
.fi-welcome .fi-logo { margin: 0 auto 16px; width: 56px; height: 56px; font-size: 1.8rem; border-radius: 18px; }
.fi-welcome h2 { margin: 0; font-weight: 700; }
.fi-welcome p { color: #80868B; margin: 4px 0 0; }
[data-baseweb="tab-list"] { gap: 8px; }
button[data-baseweb="tab"] { border-radius: 999px; padding: 8px 20px; background: #101010; height: auto; }
button[data-baseweb="tab"] p { color: #9AA0A6; font-weight: 500; }
button[data-baseweb="tab"][aria-selected="true"] { background: #1E2A3A; }
button[data-baseweb="tab"][aria-selected="true"] p { color: #D3E3FD; }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none; }
.fi-card { background: #101010; border: 1px solid #1F1F1F; border-radius: 28px; padding: 12px 12px 16px; margin-bottom: 8px; }
.fi-card:hover { border-color: #3A4A63; }
.fi-img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 20px; display: block; margin-bottom: 12px; }
.fi-noimg { background: #181818; color: #5F6368; display: flex; align-items: center; justify-content: center; }
.fi-body { padding: 0 6px; }
.fi-title { font-size: 1.15rem; font-weight: 500; margin: 0 0 8px; }
.fi-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.fi-chip { padding: 3px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 500; background: #1E2A3A; color: #D3E3FD; }
.fi-lost { background: #4A1D1D; color: #FFB4AB; }
.fi-pending { background: #4A3B00; color: #FFDF8B; }
.fi-claimed { background: #0F3D22; color: #A8E6B8; }
.fi-desc { color: #C4C7C5; margin: 0 0 8px; font-size: 0.9rem; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.fi-meta { color: #80868B; font-size: 0.75rem; }
.fi-empty { text-align: center; color: #80868B; padding: 48px 16px; border: 1px dashed #2A2A2A; border-radius: 28px; }
.stButton > button, .stFormSubmitButton > button { background: #A8C7FA; border: none; border-radius: 999px; padding: 0.5rem 1.5rem; }
.stButton > button:hover, .stFormSubmitButton > button:hover { background: #C2D7FB; }
.stButton > button p, .stFormSubmitButton > button p { color: #062E6F; font-weight: 500; }
[data-testid="stForm"] { background: #101010; border: 1px solid #232323; border-radius: 28px; padding: 20px; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { border-radius: 16px; }
.st-key-feed_search [data-baseweb="input"] { border-radius: 999px; }
.st-key-feed_search input { padding-left: 18px; }
"""

st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)

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


def esc(value):
    return html.escape(str(value or ""))


def render_card(post, claimed=False):
    item = post.item
    status = item.tracking.current_status
    if item.image_url:
        img = f'<img class="fi-img" src="{html.escape(item.image_url, quote=True)}">'
    else:
        img = '<div class="fi-img fi-noimg">No photo</div>'
    chips = "" if claimed else f'<span class="fi-chip {STATUS_CLASS.get(status, "")}">{esc(status)}</span>'
    chips += f'<span class="fi-chip">{esc(item.campus_location)}</span><span class="fi-chip">{esc(item.category.category_name)}</span>'
    if claimed:
        remaining = days_left(item.tracking.date_claimed)
        desc = ""
        foot = f"Removed in {remaining} day(s)" if remaining is not None else ""
    else:
        desc = f'<p class="fi-desc">{esc(item.description).replace(chr(10), " ")}</p>'
        foot = f"Posted by {esc(post.user.username)} on {esc(post.date_posted)}"
    st.markdown(
        f'<div class="fi-card">{img}<div class="fi-body"><div class="fi-title">{esc(item.item_name)}</div>'
        f'<div class="fi-chips">{chips}</div>{desc}<div class="fi-meta">{foot}</div></div></div>',
        unsafe_allow_html=True,
    )


def render_grid(posts, claimed=False):
    for i in range(0, len(posts), 2):
        cols = st.columns(2, gap="medium")
        for col, post in zip(cols, posts[i:i + 2]):
            with col:
                render_card(post, claimed=claimed)


def empty_state(message):
    st.markdown(f'<div class="fi-empty">{esc(message)}</div>', unsafe_allow_html=True)


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

# --- AUTHENTICATION ---
if not st.session_state.current_user:
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown(
            f'<div class="fi-welcome"><div class="fi-logo">F</div><h2>Welcome to FoundIt</h2>'
            f'<p>{esc(school.get_details())}</p></div>',
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            email = st.text_input("Institutional Email")
            password = st.text_input("Password", type="password")
            submit_login = st.form_submit_button("Login", use_container_width=True)

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
    user = st.session_state.current_user
    role = "Administrator" if user.is_admin else "Student/Faculty"

    # --- APP BAR ---
    c_brand, c_user, c_out = st.columns([5, 3, 1.5], vertical_alignment="center")
    with c_brand:
        st.markdown(
            f'<div class="fi-brand"><div class="fi-logo">F</div><div><div class="fi-name">FoundIt</div>'
            f'<div class="fi-sub">{esc(school.get_details())}</div></div></div>',
            unsafe_allow_html=True,
        )
    with c_user:
        st.markdown(
            f'<div class="fi-user"><div class="fi-avatar">{esc(user.username[:1].upper())}</div>'
            f'<div><div class="fi-uname">{esc(user.username)}</div><div class="fi-role">{role}</div></div></div>',
            unsafe_allow_html=True,
        )
    with c_out:
        if st.button("Logout", use_container_width=True):
            st.session_state.current_user = None
            st.session_state.logged_out = True
            st.session_state.pending_delete = True
            st.rerun()

    if not user.is_admin:
        st.caption("Standard account: only administrators can report or update items.")

    tab_names = ["Feed", "Claimed"] + (["Report", "Update status"] if user.is_admin else [])
    tabs = st.tabs(tab_names)

    # --- 1. FEED (active items only) ---
    with tabs[0]:
        col_search, col_campus = st.columns([3, 1])
        with col_search:
            search_query = st.text_input(
                "Search", "", key="feed_search", placeholder="Search by name, category or description",
                label_visibility="collapsed",
            ).strip().lower()
        with col_campus:
            campus_filter = st.selectbox(
                "Campus", ["All Campuses"] + CAMPUS_LOCATIONS, key="feed_campus", label_visibility="collapsed"
            )

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
            empty_state("No items match your search or filter.")
        else:
            st.caption(f"{len(posts_to_display)} item(s)")
            render_grid(posts_to_display)

    # --- 2. CLAIMED ITEMS (kept for 7 days, then auto-purged) ---
    with tabs[1]:
        st.caption(f"Claimed items stay here for {CLAIMED_RETENTION_DAYS} days, then are removed automatically.")
        claimed_campus = st.selectbox(
            "Campus", ["All Campuses"] + CAMPUS_LOCATIONS, key="claimed_campus", label_visibility="collapsed"
        )

        claimed_posts = [
            p for p in st.session_state.posts[::-1]
            if p.item.tracking.current_status == "Claimed"
        ]
        if claimed_campus != "All Campuses":
            claimed_posts = [p for p in claimed_posts if p.item.campus_location == claimed_campus]

        if not claimed_posts:
            empty_state("No claimed items.")
        else:
            render_grid(claimed_posts, claimed=True)

    if user.is_admin:
        # --- 3. REPORT ITEM (Admin Only) ---
        with tabs[2]:
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
        with tabs[3]:
            # Show the message saved before the rerun, then clear it
            if st.session_state.status_msg:
                st.success(st.session_state.status_msg)
                st.session_state.status_msg = None

            if not st.session_state.posts:
                empty_state("No items available to update.")
            else:
                post_options = {p.post_id: p for p in st.session_state.posts}
                selected_id = st.selectbox(
                    "Select Item to Update",
                    list(post_options.keys()),
                    format_func=lambda pid: f"{post_options[pid].item.item_name} ({post_options[pid].item.tracking.current_status}) - {post_options[pid].user.username}",
                )
                target_post = post_options[selected_id]
                new_status = st.radio("Select New Status", ["Lost", "Pending Claim", "Claimed"], horizontal=True)

                if st.button("Apply Status Update"):
                    target_post.item.tracking.update_tracking_status(new_status)
                    update_status_in_supabase(target_post.post_id, new_status)
                    st.session_state.posts = load_database(st.session_state.categories)
                    st.session_state.status_msg = f"Status updated to **{new_status}** in Supabase!"
                    st.rerun()
