# app.py
import html
import datetime
from abc import ABC, abstractmethod
from urllib.parse import quote

import streamlit as st
import extra_streamlit_components as stx

from models import (AuthService, CategoryCatalog, Institution, LostAndFoundService,
                    Status, SupabaseImageStorage, SupabasePostRepository, ValidationError, get_gateway)


# ---------------------------------------------------------------- UI redesign

class Theme:
    CSS = """
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
[data-testid="stBaseButton-pills"], [data-testid="stBaseButton-pillsActive"] { border-radius: 999px !important; padding: 6px 18px !important; }
[data-testid="stBaseButton-pillsActive"] { background: #A8C7FA !important; border-color: #A8C7FA !important; }
[data-testid="stBaseButton-pillsActive"] p { color: #062E6F !important; font-weight: 500; }
.st-key-grid_col_0, .st-key-grid_col_1 { gap: 1rem !important; }
[class*="st-key-card_"] { background: #101010; border: 1px solid #1F1F1F; border-radius: 28px; padding: 12px; gap: 0.6rem; }
[class*="st-key-card_"]:hover { border-color: #3A4A63; }
.fi-img { width: 100%; aspect-ratio: 4 / 3; background-size: cover; background-position: center; border-radius: 20px; }
.fi-noimg { background: #181818; color: #5F6368; display: flex; align-items: center; justify-content: center; }
.fi-body { padding: 8px 6px 4px; }
.fi-title { font-size: 1.15rem; font-weight: 500; margin: 0 0 8px; }
.fi-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.fi-chip { padding: 3px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 500; background: #1E2A3A; color: #D3E3FD; }
.fi-lost { background: #4A1D1D; color: #FFB4AB; }
.fi-pending { background: #4A3B00; color: #FFDF8B; }
.fi-claimed { background: #0F3D22; color: #A8E6B8; }
.fi-desc { color: #C4C7C5; margin: 0 0 8px; font-size: 0.9rem; }
.fi-meta { color: #80868B; font-size: 0.75rem; }
.fi-empty { text-align: center; color: #80868B; padding: 48px 16px; border: 1px dashed #2A2A2A; border-radius: 28px; }
.stButton > button, .stFormSubmitButton > button { width: 100%; background: #A8C7FA; border: none; border-radius: 999px; padding: 0.5rem 1.5rem; }
.stButton > button:hover, .stFormSubmitButton > button:hover { background: #C2D7FB; }
.stButton > button p, .stFormSubmitButton > button p { color: #062E6F; font-weight: 500; }
.st-key-logout button { background: transparent !important; border: 1px solid #2A2A2A !important; }
.st-key-logout button p { color: #C4C7C5 !important; }
[data-testid="stForm"] { background: #101010; border: 1px solid #232323; border-radius: 28px; padding: 20px; }
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { border-radius: 16px !important; }
.st-key-feed_search [data-baseweb="input"], .st-key-feed_search [data-baseweb="base-input"], .st-key-feed_search input { border-radius: 999px !important; }
.st-key-feed_search input { padding-left: 18px !important; }
.st-key-feed_campus [data-baseweb="select"] > div { border-radius: 999px !important; }
"""

    @classmethod
    def apply(cls):
        st.markdown(f"<style>{cls.CSS}</style>", unsafe_allow_html=True)


class Html:
    @staticmethod
    def esc(value):
        return html.escape(str(value or ""))


class EmptyState:
    @staticmethod
    def show(message):
        st.markdown(f'<div class="fi-empty">{Html.esc(message)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- session + cookies

class SessionField:
    """Descriptor: an attribute stored in st.session_state."""

    def __init__(self, default=None):
        self._default = default

    def __set_name__(self, owner, name):
        self._key = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return st.session_state.setdefault(self._key, self._default)

    def __set__(self, obj, value):
        st.session_state[self._key] = value


class AppState:
    current_user = SessionField()
    logged_out = SessionField(False)
    pending_token = SessionField()
    pending_delete = SessionField(False)
    status_msg = SessionField()
    report_n = SessionField(0)
    report_msg = SessionField()
    service = SessionField()

    def reset_navigation(self):
        st.session_state.pop("nav", None)


class CookieSession:
    NAME = "foundit_refresh_token"
    DAYS = 7

    def __init__(self, state, auth):
        self._state = state
        self._auth = auth
        self._cookies = stx.CookieManager()

    def restore(self):  # auto-login, survives page refresh
        state = self._state
        if state.current_user or state.logged_out:
            return
        token = self._cookies.get(self.NAME)
        if token:
            result = self._auth.restore(token)
            if result.success:
                state.current_user = result.user
                state.pending_token = result.refresh_token
                st.rerun()

    def sync(self):  # write / clear the cookie safely
        state = self._state
        if state.pending_token and state.current_user:
            self._cookies.set(
                self.NAME,
                state.pending_token,
                expires_at=datetime.datetime.now() + datetime.timedelta(days=self.DAYS),
            )
            state.pending_token = None
        if state.pending_delete and not state.current_user:
            self._cookies.delete(self.NAME)
            state.pending_delete = False


# ---------------------------------------------------------------- views

class PostCardView:
    STATUS_CLASS = {Status.LOST: "fi-lost", Status.PENDING: "fi-pending", Status.CLAIMED: "fi-claimed"}

    def __init__(self, post, claimed=False, retention_days=7):
        self._post = post
        self._claimed = claimed
        self._retention_days = retention_days

    def _media(self):
        item = self._post.item
        if item.image_url:
            style = f"background-image:url('{quote(item.image_url, safe=':/?=&%#')}')"
            return f'<div class="fi-img" style="{style}"></div>'
        return '<div class="fi-img fi-noimg">No photo</div>'

    def _chips(self):
        item = self._post.item
        status = item.tracking.status
        chips = "" if self._claimed else f'<span class="fi-chip {self.STATUS_CLASS[status]}">{Html.esc(status.value)}</span>'
        chips += f'<span class="fi-chip">{Html.esc(item.campus_location)}</span><span class="fi-chip">{Html.esc(item.category.name)}</span>'
        return chips

    def _footer(self):
        if self._claimed:
            remaining = self._post.item.tracking.days_left(self._retention_days)
            return f"Removed in {remaining} day(s)" if remaining is not None else ""
        return f"Posted by {Html.esc(self._post.user.username)} on {Html.esc(self._post.date_posted)}"

    def html(self):
        item = self._post.item
        desc = "" if self._claimed else f'<p class="fi-desc">{Html.esc(item.description).replace(chr(10), "<br>")}</p>'
        return (
            f'{self._media()}<div class="fi-body"><div class="fi-title">{Html.esc(item.name)}</div>'
            f'<div class="fi-chips">{self._chips()}</div>{desc}<div class="fi-meta">{self._footer()}</div></div>'
        )

    def render(self, key=None):
        with st.container(key=key or f"card_{self._post.post_id}"):
            st.markdown(self.html(), unsafe_allow_html=True)


class PostGrid:
    def __init__(self, posts, claimed=False, retention_days=7):
        self._posts = posts
        self._claimed = claimed
        self._retention_days = retention_days

    def render(self):
        cols = st.columns(2, gap="small")
        for idx, col in enumerate(cols):
            with col:
                with st.container(key=f"grid_col_{idx}"):
                    for post in self._posts[idx::2]:
                        PostCardView(post, self._claimed, self._retention_days).render()


class LoginView:
    def __init__(self, auth, state, institution):
        self._auth = auth
        self._state = state
        self._institution = institution

    def render(self):
        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            st.markdown(
                f'<div class="fi-welcome"><div class="fi-logo">F</div><h2>Welcome to FoundIt</h2>'
                f'<p>{Html.esc(self._institution.get_details())}</p></div>',
                unsafe_allow_html=True,
            )
            with st.form("login_form"):
                email = st.text_input("Institutional Email")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Login")

                if submitted:
                    result = self._auth.login(email, password)
                    if result.success:
                        self._state.current_user = result.user
                        self._state.logged_out = False
                        self._state.pending_token = result.refresh_token
                        st.rerun()
                    else:
                        st.error(f"Authentication failed: {result.error}")


class AppBar:
    def __init__(self, institution, user):
        self._institution = institution
        self._user = user

    def render(self):  # returns True when Logout was clicked
        c_brand, c_user, c_out = st.columns([5, 3, 1.5], vertical_alignment="center")
        with c_brand:
            st.markdown(
                f'<div class="fi-brand"><div class="fi-logo">F</div><div><div class="fi-name">FoundIt</div>'
                f'<div class="fi-sub">{Html.esc(self._institution.get_details())}</div></div></div>',
                unsafe_allow_html=True,
            )
        with c_user:
            st.markdown(
                f'<div class="fi-user"><div class="fi-avatar">{Html.esc(self._user.avatar_initial)}</div>'
                f'<div><div class="fi-uname">{Html.esc(self._user.username)}</div>'
                f'<div class="fi-role">{Html.esc(self._user.role_label)}</div></div></div>',
                unsafe_allow_html=True,
            )
        with c_out:
            return st.button("Logout", key="logout")


# ---------------------------------------------------------------- pages

class Page(ABC):
    title = ""
    ALL_CAMPUSES = "All Campuses"

    def __init__(self, service, state):
        self._service = service
        self._state = state

    def _campus_filter(self, key):
        options = [self.ALL_CAMPUSES] + self._service.institution.campuses
        choice = st.selectbox("Campus", options, key=key, label_visibility="collapsed")
        return None if choice == self.ALL_CAMPUSES else choice

    @abstractmethod
    def render(self, user):
        ...


class AdminPage(Page):
    def render(self, user):
        if not user.can_manage_items():
            st.error("Only administrators can open this page.")
            return
        self._render(user)

    @abstractmethod
    def _render(self, user):
        ...


class FeedPage(Page):
    title = "Feed"

    def render(self, user):
        col_search, col_campus = st.columns([3, 1])
        with col_search:
            query = st.text_input(
                "Search", "", key="feed_search", placeholder="Search by name, category or description",
                label_visibility="collapsed",
            )
        with col_campus:
            campus = self._campus_filter("feed_campus")

        posts = self._service.active(campus, query)
        if not posts:
            EmptyState.show("No items match your search or filter.")
        else:
            PostGrid(posts, retention_days=self._service.RETENTION_DAYS).render()


class ClaimedPage(Page):
    title = "Claimed"

    def render(self, user):
        st.caption(f"Claimed items stay here for {self._service.RETENTION_DAYS} days, then are removed automatically.")
        campus = self._campus_filter("claimed_campus")

        posts = self._service.claimed(campus)
        if not posts:
            EmptyState.show("No claimed items.")
        else:
            PostGrid(posts, claimed=True, retention_days=self._service.RETENTION_DAYS).render()


class ReportPage(AdminPage):
    title = "Report"

    def _photo_section(self, rk):
        return st.file_uploader("Item Photo", type=["jpg", "jpeg", "png"], key=f"r_photo_{rk}")

    def _details_section(self, user, rk, photo):
        name = st.text_input("Item Name", key=f"r_name_{rk}")
        description = st.text_area("Description / Distinguishing Features", key=f"r_desc_{rk}")
        campus = st.selectbox("Campus Holding Office", self._service.institution.campuses, key=f"r_campus_{rk}")
        category = st.selectbox("Category", self._service.catalog.names(), key=f"r_cat_{rk}")

        if st.button("Post Item", key="post_item"):
            try:
                self._service.report(user, name, description, category, campus, photo)
            except ValidationError as e:
                st.warning(str(e))
            else:
                self._state.report_n += 1
                self._state.report_msg = "Item posted successfully and saved to Supabase!"
                st.rerun()

    def _render(self, user):
        rk = self._state.report_n
        if self._state.report_msg:
            st.success(self._state.report_msg)
            self._state.report_msg = None

        left, right = st.columns(2, gap="large")
        with left:
            photo = self._photo_section(rk)
        with right:
            self._details_section(user, rk, photo)


class UpdateStatusPage(AdminPage):
    title = "Update status"

    @staticmethod
    def _label(post):
        return f"{post.item.name} ({post.item.tracking.status.value}) - {post.user.username}"

    def _render(self, user):
        if self._state.status_msg:  # message saved before the rerun
            st.success(self._state.status_msg)
            self._state.status_msg = None

        posts = list(reversed(self._service.posts))
        if not posts:
            EmptyState.show("No items available to update.")
            return

        by_id = {p.post_id: p for p in posts}
        left, right = st.columns(2, gap="large")
        with left:
            selected_id = st.selectbox(
                "Select Item to Update", list(by_id.keys()), format_func=lambda pid: self._label(by_id[pid])
            )
            new_status = st.radio("Select New Status", [s.value for s in Status], horizontal=True)
            apply_update = st.button("Apply Status Update")
        with right:
            PostCardView(by_id[selected_id], retention_days=self._service.RETENTION_DAYS).render(key="card_preview")

        if apply_update:
            self._service.set_status(user, selected_id, new_status)
            self._state.status_msg = f"Status updated to **{new_status}** in Supabase!"
            st.rerun()


# ---------------------------------------------------------------- application

class FoundItApp:
    PAGES = (FeedPage, ClaimedPage, ReportPage, UpdateStatusPage)

    def __init__(self):
        self._gateway = get_gateway()
        self._state = AppState()
        self._auth = AuthService(self._gateway)
        self._cookies = CookieSession(self._state, self._auth)
        self._institution = Institution("Mapúa Malayan Colleges Mindanao", "Davao City", ["RSY Building", "RG Birrey"])

    def _service(self):
        if self._state.service is None:
            catalog = CategoryCatalog.default()
            repository = SupabasePostRepository(
                self._gateway, catalog, SupabaseImageStorage(self._gateway), self._institution.default_campus
            )
            self._state.service = LostAndFoundService(repository, catalog, self._institution)
        return self._state.service

    def _logout(self):
        self._state.current_user = None
        self._state.logged_out = True
        self._state.pending_delete = True
        self._state.service = None
        self._state.reset_navigation()
        st.rerun()

    def _render_main(self, user):
        service = self._service()
        service.refresh_if_stale()
        if AppBar(self._institution, user).render():
            self._logout()

        if not user.can_manage_items():
            st.caption("Standard account: only administrators can report or update items.")

        navigation = st.pills(
            "Section", user.sections(), default="Feed", key="nav", label_visibility="collapsed"
        ) or "Feed"
        pages = {cls.title: cls(service, self._state) for cls in self.PAGES}
        pages.get(navigation, pages["Feed"]).render(user)

    def run(self):
        Theme.apply()
        self._cookies.restore()
        self._cookies.sync()
        user = self._state.current_user
        if user is None:
            LoginView(self._auth, self._state, self._institution).render()
        else:
            self._render_main(user)


def main():
    st.set_page_config(page_title="FoundIt - Campus Lost & Found", page_icon="", layout="centered")
    FoundItApp().run()


main()
