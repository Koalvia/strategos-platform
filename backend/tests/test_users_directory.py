"""Tests for the read-only users (Usuarios) directory (issue #11).

The directory joins the local ``auth.User`` rows (name, role, email — identity
stays local) with each user's active-task count derived from the fixture-backed
``MockBusinessCentralClient``. These tests cover:

* the seed creating the 6 staff users with the documented roles and no usable
  password (and being idempotent),
* the endpoint returning name/role/email/active_tasks per user with the active
  count computed from the mock BC ``userTasks`` (non-"Hecho" tasks), and
* that the endpoint rejects unauthenticated requests.

Active-task counts are computed from the mock BC data: a local user is matched to
their BC assignee by email, then their non-done tasks are counted. Against the
current fixtures this yields Marc 2, Anna 3, Laura 2, Jordi 3, Núria 2, Pol 1.
"""

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user, verify_password
from app.main import app
from scripts.seed_staff_users import STAFF, seed_staff_users

USERS_URL = "/api/v1/users"

# active_tasks computed from the mock BC fixtures (non-"Hecho" tasks per assignee).
EXPECTED_ACTIVE = {
    "marc@estrategos.ad": 2,
    "anna@estrategos.ad": 3,
    "laura@estrategos.ad": 2,
    "jordi@estrategos.ad": 3,
    "nuria@estrategos.ad": 2,
    "pol@estrategos.ad": 1,
}


@pytest.fixture
def seeded_client(db_session):
    """A client whose database holds the seeded staff users."""
    seed_staff_users(db_session)
    # Authenticate as one of the seeded staff (any verified user is fine).
    current = db_session.query(User).filter(User.email == "marc@estrategos.ad").one()
    current.is_verified = True
    db_session.commit()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_verified_user] = lambda: current
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_seed_creates_staff_with_roles(db_session):
    """The seed creates the 6 staff users with the documented roles."""
    seed_staff_users(db_session)

    users = db_session.query(User).order_by(User.id.asc()).all()
    assert [(u.name, u.role, u.email) for u in users] == STAFF
    assert len(users) == 6


@pytest.mark.unit
def test_seed_password_is_unusable(db_session):
    """Seeded users get a hash that no known password validates against."""
    seed_staff_users(db_session)

    for user in db_session.query(User).all():
        assert user.hashed_password
        # The seed hashes a discarded random secret, so common guesses must fail.
        assert not verify_password("", user.hashed_password)
        assert not verify_password(user.email, user.hashed_password)
        assert not verify_password("password", user.hashed_password)


@pytest.mark.unit
def test_seed_is_idempotent(db_session):
    """Re-seeding does not duplicate users and refreshes name/role in place."""
    seed_staff_users(db_session)
    # Corrupt a role to prove the second run repairs it.
    laura = db_session.query(User).filter(User.email == "laura@estrategos.ad").one()
    laura.role = "Wrong Role"
    db_session.commit()

    seed_staff_users(db_session)

    assert db_session.query(User).count() == 6
    laura = db_session.query(User).filter(User.email == "laura@estrategos.ad").one()
    assert laura.role == "Responsable Laboral"


# --------------------------------------------------------------------------- #
# Model default
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_role_defaults_to_null(db_session):
    """A user created without a role has ``role`` null (nullable column)."""
    user = User(
        name="No Role",
        email="norole@example.com",
        hashed_password="not-a-real-hash",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.role is None


# --------------------------------------------------------------------------- #
# Directory endpoint
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_directory_returns_fields_and_counts(seeded_client):
    """The endpoint returns name/role/email/active_tasks for every staff user."""
    resp = seeded_client.get(USERS_URL)
    assert resp.status_code == 200
    body = resp.json()

    assert len(body) == 6
    assert set(body[0].keys()) == {"name", "role", "email", "active_tasks"}

    by_email = {row["email"]: row for row in body}
    assert by_email["laura@estrategos.ad"]["role"] == "Responsable Laboral"
    assert by_email["pol@estrategos.ad"]["role"] == "Administració"

    for email, expected in EXPECTED_ACTIVE.items():
        assert by_email[email]["active_tasks"] == expected


@pytest.mark.integration
def test_directory_preserves_seed_order(seeded_client):
    """Users are listed in the mock's display order (by insertion id)."""
    resp = seeded_client.get(USERS_URL)
    emails = [row["email"] for row in resp.json()]
    assert emails == [email for _, _, email in STAFF]


@pytest.mark.integration
def test_directory_user_without_bc_match_has_zero(db_session):
    """A local user with no matching BC user shows 0 active tasks."""
    seed_staff_users(db_session)
    outsider = User(
        name="Outsider",
        email="outsider@example.com",
        role="Administració",
        hashed_password="not-a-real-hash",
        is_verified=True,
    )
    db_session.add(outsider)
    db_session.commit()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_verified_user] = lambda: outsider
    with TestClient(app) as test_client:
        body = test_client.get(USERS_URL).json()
    app.dependency_overrides.clear()

    by_email = {row["email"]: row for row in body}
    assert by_email["outsider@example.com"]["active_tasks"] == 0


@pytest.mark.integration
def test_directory_requires_authentication():
    """Without a verified user the endpoint returns 401/403."""
    with TestClient(app) as test_client:
        resp = test_client.get(USERS_URL)
    assert resp.status_code in (401, 403)
