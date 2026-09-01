"""Shared pytest fixtures for the backend test suite.

This is the first test harness in the repository. It boots the real FastAPI
app against an in-memory SQLite database and overrides the two request-scoped
dependencies tests care about:

* ``get_db`` -> a session bound to the throwaway SQLite engine.
* ``get_verified_user`` -> a seeded, verified user, so endpoints can be hit
  without minting JWTs.

The API-key middleware and Sentry are already disabled when ``TESTING=1`` (see
``app.main``), which the runner sets. We default the env here too so the suite
also works under a bare ``pytest`` invocation.
"""

import os
from typing import Generator

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
# Force the mock BC client regardless of a developer's local .env: pydantic-settings
# reads .env directly (not just os.environ), so a local BUSINESS_CENTRAL_MODE=live
# would otherwise make the suite issue real network calls to Business Central.
os.environ["BUSINESS_CENTRAL_MODE"] = "mock"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_customer_scope
from app.core.visibility import CustomerScope
from app.db.base import Base
from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.main import app

# Importing the models above (plus those pulled in transitively by ``app.main``)
# registers every table on ``Base.metadata`` so ``create_all`` builds the schema.


@pytest.fixture
def db_session():
    """A SQLAlchemy session on a fresh in-memory database, dropped after each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def test_user(db_session) -> User:
    """A verified user that owns the data created in tests."""
    user = User(
        name="Test User",
        email="test@example.com",
        hashed_password="not-a-real-hash",
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session, test_user) -> Generator[TestClient, None, None]:
    """A TestClient wired to the in-memory DB and authenticated as ``test_user``.

    The customer scope is pinned to "sees everything" so these tests keep asserting
    against the whole fixture set; scoping is covered by its own two test modules.
    """
    app.dependency_overrides.clear()

    def override_get_db():
        yield db_session

    def override_get_verified_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_verified_user] = override_get_verified_user
    app.dependency_overrides[get_customer_scope] = lambda: CustomerScope(
        customer_ids=None, reason="test-unrestricted"
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def bopa_bulletin_factory(db_session):
    """Factory to create BopaBulletin instances for testing."""
    from datetime import datetime

    from app.domains.bopa.models import BopaBulletin

    def _create_bulletin(year=2026, num=1, is_extra=False, total_document_count=2):
        bulletin = BopaBulletin(
            year=year,
            num=num,
            is_extra=is_extra,
            published_at=datetime(year, 1, 1),
            total_document_count=total_document_count,
            sumari_pdf_url=f"https://example.com/sumari_{year}_{num}.pdf",
        )
        db_session.add(bulletin)
        db_session.flush()  # Assign ID without committing
        return bulletin

    return _create_bulletin

