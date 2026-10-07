# models.py
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from enum import Enum

import streamlit as st
from supabase import create_client, Client


class ValidationError(ValueError):
    pass


class Status(str, Enum):
    LOST = "Lost"
    PENDING = "Pending Claim"
    CLAIMED = "Claimed"

    @classmethod
    def parse(cls, value):
        try:
            return cls(value)
        except ValueError:
            return cls.LOST


# ---------------------------------------------------------------- infrastructure

class SupabaseGateway:
    def __init__(self):
        self._url = st.secrets["SUPABASE_URL"]
        self._anon_key = st.secrets["SUPABASE_KEY"]
        self._reader = create_client(self._url, self._anon_key)
        self._writer = create_client(self._url, st.secrets["SUPABASE_SERVICE_KEY"])

    @property
    def reader(self) -> Client:  # anon, read-only use
        return self._reader

    @property
    def writer(self) -> Client:  # service role, writes only
        return self._writer

    def new_auth_client(self) -> Client:  # throwaway, one per login
        return create_client(self._url, self._anon_key)


@st.cache_resource
def get_gateway() -> SupabaseGateway:
    return SupabaseGateway()


# ---------------------------------------------------------------- domain entities

class Institution:
    def __init__(self, name, city, campuses):
        self._name = name
        self._city = city
        self._campuses = list(campuses)

    @property
    def name(self):
        return self._name

    @property
    def city(self):
        return self._city

    @property
    def campuses(self):
        return list(self._campuses)

    @property
    def default_campus(self):
        return self._campuses[0]

    def get_details(self):
        return f"{self._name} - {self._city}"


class Category:
    def __init__(self, name, code):
        self._name = name
        self._code = code

    @property
    def name(self):
        return self._name

    @property
    def code(self):
        return self._code


class CategoryCatalog:
    def __init__(self, categories, fallback_name):
        self._categories = list(categories)
        self._fallback_name = fallback_name

    @classmethod
    def default(cls):
        return cls([
            Category("Electronics", "CAT-01"),
            Category("Tumblers/Bottles", "CAT-02"),
            Category("IDs/Cards", "CAT-03"),
            Category("Others", "CAT-04"),
        ], fallback_name="Others")

    def all(self):
        return list(self._categories)

    def names(self):
        return [c.name for c in self._categories]

    def find(self, name):
        by_name = {c.name: c for c in self._categories}
        return by_name.get(name) or by_name[self._fallback_name]


class Tracking:
    def __init__(self, status=Status.LOST, date_claimed=None):
        self._status = Status.parse(status)
        self._date_claimed = date_claimed

    @property
    def status(self):
        return self._status

    @property
    def date_claimed(self):
        return self._date_claimed

    @property
    def is_claimed(self):
        return self._status is Status.CLAIMED

    def update(self, new_status):
        self._status = Status(new_status)  # raises ValueError if invalid
        self._date_claimed = datetime.now(timezone.utc).isoformat() if self.is_claimed else None

    def days_left(self, retention_days):
        try:
            claimed_at = datetime.fromisoformat(str(self._date_claimed).replace("Z", "+00:00"))
            if claimed_at.tzinfo is None:
                claimed_at = claimed_at.replace(tzinfo=timezone.utc)
            remaining = claimed_at + timedelta(days=retention_days) - datetime.now(timezone.utc)
            return max(remaining.days, 0)
        except (TypeError, ValueError):
            return None


class Item:
    def __init__(self, name, description, category, campus_location, image_url=None, tracking=None):
        self._name = name
        self._description = description or ""
        self._category = category
        self._campus_location = campus_location
        self._image_url = image_url
        self._tracking = tracking or Tracking()

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def category(self):
        return self._category

    @property
    def campus_location(self):
        return self._campus_location

    @property
    def image_url(self):
        return self._image_url

    @property
    def tracking(self):
        return self._tracking

    def attach_image(self, url):
        self._image_url = url

    def matches(self, query):
        q = (query or "").strip().lower()
        if not q:
            return True
        return q in self._name.lower() or q in self._category.name.lower() or q in self._description.lower()


# ---------------------------------------------------------------- users

class User(ABC):
    BASE_SECTIONS = ["Feed", "Claimed"]

    def __init__(self, username, institutional_id):
        self._username = username
        self._institutional_id = institutional_id

    @property
    def username(self):
        return self._username

    @property
    def institutional_id(self):
        return self._institutional_id

    @property
    def avatar_initial(self):
        return self._username[:1].upper()

    @property
    @abstractmethod
    def role_label(self):
        ...

    @abstractmethod
    def can_manage_items(self):
        ...

    @abstractmethod
    def sections(self):
        ...


class StandardUser(User):
    @property
    def role_label(self):
        return "Student/Faculty"

    def can_manage_items(self):
        return False

    def sections(self):
        return list(self.BASE_SECTIONS)


class Administrator(User):
    @property
    def role_label(self):
        return "Administrator"

    def can_manage_items(self):
        return True

    def sections(self):
        return self.BASE_SECTIONS + ["Report", "Update status"]


class UserFactory:
    @staticmethod
    def admin_emails():
        raw = st.secrets.get("ADMIN_EMAILS", "")
        return {e.strip().lower() for e in raw.split(",") if e.strip()}

    @classmethod
    def create(cls, email, username=None):
        username = username or (email or "").split("@")[0]
        if email and email.strip().lower() in cls.admin_emails():
            return Administrator(username, email)
        return StandardUser(username, email)


class Post:
    def __init__(self, post_id, date_posted, user, item):
        self._post_id = post_id
        self._date_posted = date_posted
        self._user = user
        self._item = item

    @classmethod
    def create(cls, user, item):
        post_id = f"POST-{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:6]}"
        return cls(post_id, datetime.now().strftime("%Y-%m-%d"), user, item)

    @classmethod
    def from_record(cls, record, catalog, default_campus):
        item = Item(
            record["item_name"],
            record.get("description"),
            catalog.find(record.get("category_name")),
            record.get("campus_location") or default_campus,
            record.get("image_url"),
            Tracking(record.get("status", Status.LOST), record.get("date_claimed")),
        )
        user = UserFactory.create(record["institutional_id"], record.get("username"))
        return cls(record["post_id"], record["date_posted"], user, item)

    @property
    def post_id(self):
        return self._post_id

    @property
    def tracking_id(self):
        return f"TRK-{self._post_id}"

    @property
    def date_posted(self):
        return self._date_posted

    @property
    def user(self):
        return self._user

    @property
    def item(self):
        return self._item

    def matches(self, query):
        return self._item.matches(query)

    def to_record(self):
        return {
            "post_id": self._post_id,
            "date_posted": self._date_posted,
            "username": self._user.username,
            "institutional_id": self._user.institutional_id,
            "item_name": self._item.name,
            "description": self._item.description,
            "category_name": self._item.category.name,
            "campus_location": self._item.campus_location,
            "image_url": self._item.image_url,
            "status": self._item.tracking.status.value,
            "date_claimed": self._item.tracking.date_claimed,
        }


# ---------------------------------------------------------------- authentication

class AuthResult:
    def __init__(self, user=None, refresh_token=None, error=None):
        self.user = user
        self.refresh_token = refresh_token
        self.error = error

    @property
    def success(self):
        return self.user is not None


class AuthService:
    def __init__(self, gateway):
        self._gateway = gateway

    def login(self, email, password):
        try:
            client = self._gateway.new_auth_client()
            response = client.auth.sign_in_with_password({"email": email, "password": password})
            return AuthResult(UserFactory.create(response.user.email), response.session.refresh_token)
        except Exception as e:
            return AuthResult(error=str(e))

    def restore(self, refresh_token):
        try:
            client = self._gateway.new_auth_client()
            response = client.auth.refresh_session(refresh_token)
            if not response.user or not response.session:
                return AuthResult(error="No user/session returned")
            return AuthResult(UserFactory.create(response.user.email), response.session.refresh_token)
        except Exception as e:
            return AuthResult(error=str(e))


# ---------------------------------------------------------------- persistence

class ImageStorage(ABC):
    @abstractmethod
    def upload(self, post_id, image):
        ...

    @abstractmethod
    def delete(self, url):
        ...


class SupabaseImageStorage(ImageStorage):
    BUCKET = "item-images"

    def __init__(self, gateway):
        self._gateway = gateway

    def _bucket(self):
        return self._gateway.writer.storage.from_(self.BUCKET)

    def upload(self, post_id, image):
        path = f"{post_id}.{image.name.split('.')[-1]}"
        self._bucket().upload(
            path=path,
            file=image.getvalue(),
            file_options={"content-type": image.type, "upsert": "true"},
        )
        return self._bucket().get_public_url(path)

    def delete(self, url):
        try:
            self._bucket().remove([url.split("?")[0].split("/")[-1]])
        except Exception as e:
            print(f"Error deleting image from storage: {e}")


class PostRepository(ABC):
    @abstractmethod
    def all(self):
        ...

    @abstractmethod
    def add(self, post, image=None):
        ...

    @abstractmethod
    def save_status(self, post):
        ...

    @abstractmethod
    def purge_expired(self, retention_days):
        ...


class SupabasePostRepository(PostRepository):
    TABLE = "posts"

    def __init__(self, gateway, catalog, storage, default_campus):
        self._gateway = gateway
        self._catalog = catalog
        self._storage = storage
        self._default_campus = default_campus

    def all(self):
        rows = self._gateway.reader.table(self.TABLE).select("*").execute().data or []
        posts = [Post.from_record(r, self._catalog, self._default_campus) for r in rows]
        return sorted(posts, key=lambda p: p.post_id)  # oldest first

    def add(self, post, image=None):
        if image is not None:
            post.item.attach_image(self._storage.upload(post.post_id, image))
        self._gateway.writer.table(self.TABLE).insert(post.to_record()).execute()

    def save_status(self, post):
        tracking = post.item.tracking
        self._gateway.writer.table(self.TABLE).update({
            "status": tracking.status.value,
            "date_claimed": tracking.date_claimed,
        }).eq("post_id", post.post_id).execute()

    def purge_expired(self, retention_days):
        threshold = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        expired = self._gateway.writer.table(self.TABLE) \
            .select("post_id, image_url") \
            .eq("status", Status.CLAIMED.value) \
            .lt("date_claimed", threshold) \
            .execute().data or []
        for row in expired:
            if row.get("image_url"):
                self._storage.delete(row["image_url"])
            self._gateway.writer.table(self.TABLE).delete().eq("post_id", row["post_id"]).execute()
        return len(expired)


# ---------------------------------------------------------------- application service

class LostAndFoundService:
    RETENTION_DAYS = 7
    STALE_AFTER = 30  # seconds before the feed reloads from the database

    def __init__(self, repository, catalog, institution):
        self._repo = repository
        self._catalog = catalog
        self._institution = institution
        self._posts = []
        self._loaded_at = 0.0
        self.refresh()

    @property
    def catalog(self):
        return self._catalog

    @property
    def institution(self):
        return self._institution

    @property
    def posts(self):
        return list(self._posts)

    def refresh(self):
        self._repo.purge_expired(self.RETENTION_DAYS)
        self._posts = self._repo.all()
        self._loaded_at = time.monotonic()

    def refresh_if_stale(self):
        if time.monotonic() - self._loaded_at > self.STALE_AFTER:
            self.refresh()

    def find(self, post_id):
        return next(p for p in self._posts if p.post_id == post_id)

    def active(self, campus=None, query=""):
        return [
            p for p in reversed(self._posts)
            if not p.item.tracking.is_claimed
            and (campus is None or p.item.campus_location == campus)
            and p.matches(query)
        ]

    def claimed(self, campus=None):
        return [
            p for p in reversed(self._posts)
            if p.item.tracking.is_claimed
            and (campus is None or p.item.campus_location == campus)
        ]

    @staticmethod
    def _require_admin(user):
        if not user.can_manage_items():
            raise PermissionError("Only administrators can do this.")

    def report(self, user, name, description, category_name, campus, image=None):
        self._require_admin(user)
        if not (name or "").strip():
            raise ValidationError("Please provide an item name.")
        item = Item(name, description, self._catalog.find(category_name), campus)
        post = Post.create(user, item)
        self._repo.add(post, image)
        self.refresh()
        return post

    def set_status(self, user, post_id, new_status):
        self._require_admin(user)
        post = self.find(post_id)
        post.item.tracking.update(new_status)
        self._repo.save_status(post)
        self.refresh()
