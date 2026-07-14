"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service. Follows the same fixture and assertion
structure as tests/test_collection.py.
"""

import pytest
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.watchlist_service import (
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist,
    AlreadyInWatchlistError,
    NotInWatchlistError,
)
from services.collection_service import FilmNotFoundError


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Basic add ───────────────────────────────────────────────────────────────

def test_add_to_watchlist_creates_entry(app, sample_user, sample_film):
    """Adding a valid film should create a WatchlistEntry in the database."""
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry is not None
        assert entry.user_id == sample_user
        assert entry.film_id == sample_film

        in_db = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first()
        assert in_db is not None


# ── Deduplication ────────────────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice should raise AlreadyInWatchlistError,
    not silently create a duplicate entry.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyInWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── Nonexistent film (Comment 3 — equivalent of the collection test) ─────────

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.
    """
    with app.app_context():
        fake_film_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=fake_film_id)


# ── Visibility (public param) ────────────────────────────────────────────────

def test_add_to_watchlist_defaults_to_public(app, sample_user, sample_film):
    """Omitting `public` should leave the entry public (the documented default)."""
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)
        assert entry.public is True


def test_add_to_watchlist_respects_explicit_private(app, sample_user, sample_film):
    """Passing public=False should persist a private entry."""
    with app.app_context():
        entry = add_to_watchlist(
            user_id=sample_user, film_id=sample_film, public=False
        )
        assert entry.public is False


# ── Edge case (not requested in review): dedup is scoped per user ────────────

def test_same_film_on_two_users_watchlists_is_allowed(app, sample_film):
    """
    Deduplication is scoped to (user_id, film_id). Two *different* users must
    each be able to watchlist the same film — the dedup check must not treat
    the film as globally taken.
    """
    with app.app_context():
        alice = User(username="alice", email="alice@example.com")
        bob = User(username="bob", email="bob@example.com")
        db.session.add_all([alice, bob])
        db.session.commit()

        add_to_watchlist(user_id=alice.id, film_id=sample_film)
        add_to_watchlist(user_id=bob.id, film_id=sample_film)  # must not raise

        count = WatchlistEntry.query.filter_by(film_id=sample_film).count()
        assert count == 2


# ── Removal (remove_from_watchlist) ──────────────────────────────────────────

def test_remove_from_watchlist_removes_entry(app, sample_user, sample_film):
    """Removing a watchlisted film should delete its entry."""
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert remove_from_watchlist(user_id=sample_user, film_id=sample_film) is True

        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 0


def test_remove_from_watchlist_nonexistent_raises(app, sample_user, sample_film):
    """Removing a film that isn't on the watchlist should raise NotInWatchlistError."""
    with app.app_context():
        with pytest.raises(NotInWatchlistError):
            remove_from_watchlist(user_id=sample_user, film_id=sample_film)


# ── get_watchlist (join + sort order) ────────────────────────────────────────

def test_get_watchlist_returns_film_dicts_sorted_by_title(app, sample_user):
    """
    get_watchlist() should join through to Film (exercising the film
    relationship) and return film dicts sorted alphabetically by title.
    """
    with app.app_context():
        zebra = Film(title="Zodiac", year=2007, genre="Thriller")
        apple = Film(title="Amelie", year=2001, genre="Romance")
        db.session.add_all([zebra, apple])
        db.session.commit()

        add_to_watchlist(user_id=sample_user, film_id=zebra.id)
        add_to_watchlist(user_id=sample_user, film_id=apple.id)

        watchlist = get_watchlist(sample_user)
        titles = [f["title"] for f in watchlist]

        assert titles == ["Amelie", "Zodiac"]
        assert "public" in watchlist[0] and "date_added" in watchlist[0]
