"""Tests for Microsoft SSO login (Entra ID).

The Microsoft client (``app.domains.auth.microsoft``) is mocked, so no network
or Entra credentials are needed. SSO only admits emails that already exist in
``users``; it never creates accounts.
"""

import pytest
from jose import jwt

from app.core.config import settings
from app.domains.auth import microsoft
from app.domains.auth.models import User

LOGIN_URL = "/api/v1/auth/microsoft/login"
CALLBACK_URL = "/api/v1/auth/microsoft/callback"
CALLBACK_BODY = {"flow": {"state": "abc"}, "auth_response": {"code": "xyz", "state": "abc"}}


@pytest.fixture
def sso_enabled(monkeypatch):
    monkeypatch.setattr(settings, "MS_SSO_ENABLED", True)


def _mock_microsoft_email(monkeypatch, email):
    monkeypatch.setattr(microsoft, "email_from_callback", lambda flow, auth_response: email)


def test_login_start_returns_authorization_url(client, sso_enabled, monkeypatch):
    flow = {"auth_uri": "https://login.microsoftonline.com/tenant/authorize?x=1", "state": "abc"}
    monkeypatch.setattr(microsoft, "start_flow", lambda: flow)

    response = client.get(LOGIN_URL)

    assert response.status_code == 200
    assert response.json() == {"authorization_url": flow["auth_uri"], "flow": flow}


def test_callback_existing_user_gets_jwt(client, test_user, sso_enabled, monkeypatch):
    _mock_microsoft_email(monkeypatch, test_user.email)

    response = client.post(CALLBACK_URL, json=CALLBACK_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    payload = jwt.decode(body["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["sub"] == str(test_user.id)


def test_callback_matches_email_case_insensitively(client, db_session, sso_enabled, monkeypatch):
    # The Microsoft wrapper lowercases the email; the stored one may be mixed case.
    db_session.add(User(name="Mixed Case", email="Mixed.Case@example.com", hashed_password="x", is_verified=True))
    db_session.commit()
    _mock_microsoft_email(monkeypatch, "mixed.case@example.com")

    response = client.post(CALLBACK_URL, json=CALLBACK_BODY)

    assert response.status_code == 200


def test_callback_unknown_email_is_forbidden_and_creates_no_user(client, db_session, sso_enabled, monkeypatch):
    _mock_microsoft_email(monkeypatch, "stranger@example.com")
    users_before = db_session.query(User).count()

    response = client.post(CALLBACK_URL, json=CALLBACK_BODY)

    assert response.status_code == 403
    assert db_session.query(User).count() == users_before


def test_callback_unverified_user_is_forbidden(client, db_session, sso_enabled, monkeypatch):
    db_session.add(User(name="Pending", email="pending@example.com", hashed_password="x", is_verified=False))
    db_session.commit()
    _mock_microsoft_email(monkeypatch, "pending@example.com")

    response = client.post(CALLBACK_URL, json=CALLBACK_BODY)

    assert response.status_code == 403


def test_wrapper_rejects_token_without_email(monkeypatch, allowed_tenants):
    monkeypatch.setattr(microsoft, "_app", _fake_msal({"tid": KOALVIA_TID}))

    with pytest.raises(ValueError):
        microsoft.email_from_callback({}, {})


def test_callback_invalid_microsoft_response_is_unauthorized(client, sso_enabled, monkeypatch):
    def fail(flow, auth_response):
        raise ValueError("invalid_grant")

    monkeypatch.setattr(microsoft, "email_from_callback", fail)

    response = client.post(CALLBACK_URL, json=CALLBACK_BODY)

    assert response.status_code == 401


KOALVIA_TID = "f9b51fd2-8550-473d-ae84-9d4f9814e835"
STRATEGOS_TID = "e9cf8bf3-1d78-4f23-94f9-9a494d01dc4e"
FOREIGN_TID = "00000000-0000-0000-0000-000000000000"


def _fake_msal(claims):
    """Stand-in for the MSAL app returning the given id_token claims."""

    class FakeApp:
        def acquire_token_by_auth_code_flow(self, flow, auth_response):
            return {"id_token_claims": claims}

    return lambda: FakeApp()


@pytest.fixture
def allowed_tenants(monkeypatch):
    monkeypatch.setattr(settings, "MS_ALLOWED_TENANT_IDS", f"{KOALVIA_TID}, {STRATEGOS_TID}")


@pytest.mark.parametrize("tid", [KOALVIA_TID, STRATEGOS_TID])
def test_wrapper_accepts_allowed_tenants(monkeypatch, allowed_tenants, tid):
    monkeypatch.setattr(microsoft, "_app", _fake_msal({"tid": tid, "preferred_username": "Marc@Strategos.ad"}))

    assert microsoft.email_from_callback({}, {}) == "marc@strategos.ad"


def test_wrapper_rejects_unlisted_tenant(monkeypatch, allowed_tenants):
    monkeypatch.setattr(microsoft, "_app", _fake_msal({"tid": FOREIGN_TID, "preferred_username": "marc@strategos.ad"}))

    with pytest.raises(ValueError):
        microsoft.email_from_callback({}, {})


def test_wrapper_rejects_token_without_tid(monkeypatch, allowed_tenants):
    monkeypatch.setattr(microsoft, "_app", _fake_msal({"preferred_username": "marc@strategos.ad"}))

    with pytest.raises(ValueError):
        microsoft.email_from_callback({}, {})


def test_wrapper_falls_back_to_own_tenant_when_allowlist_empty(monkeypatch):
    monkeypatch.setattr(settings, "MS_ALLOWED_TENANT_IDS", "")
    monkeypatch.setattr(settings, "MS_TENANT_ID", KOALVIA_TID)

    monkeypatch.setattr(microsoft, "_app", _fake_msal({"tid": KOALVIA_TID, "preferred_username": "a@koalvia.com"}))
    assert microsoft.email_from_callback({}, {}) == "a@koalvia.com"

    monkeypatch.setattr(microsoft, "_app", _fake_msal({"tid": STRATEGOS_TID, "preferred_username": "a@strategos.ad"}))
    with pytest.raises(ValueError):
        microsoft.email_from_callback({}, {})


def test_wrapper_rejects_everyone_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(settings, "MS_ALLOWED_TENANT_IDS", "")
    monkeypatch.setattr(settings, "MS_TENANT_ID", "")
    monkeypatch.setattr(microsoft, "_app", _fake_msal({"tid": KOALVIA_TID, "preferred_username": "a@koalvia.com"}))

    with pytest.raises(ValueError):
        microsoft.email_from_callback({}, {})


def test_callback_strategos_user_signs_in_but_foreign_tenant_is_rejected(
    client, db_session, sso_enabled, allowed_tenants, monkeypatch
):
    db_session.add(User(name="Marc", email="marc@strategos.ad", hashed_password="x", is_verified=True))
    db_session.commit()

    monkeypatch.setattr(microsoft, "_app", _fake_msal({"tid": STRATEGOS_TID, "preferred_username": "marc@strategos.ad"}))
    assert client.post(CALLBACK_URL, json=CALLBACK_BODY).status_code == 200

    monkeypatch.setattr(microsoft, "_app", _fake_msal({"tid": FOREIGN_TID, "preferred_username": "marc@strategos.ad"}))
    assert client.post(CALLBACK_URL, json=CALLBACK_BODY).status_code == 401


def test_endpoints_return_404_when_sso_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "MS_SSO_ENABLED", False)

    assert client.get(LOGIN_URL).status_code == 404
    assert client.post(CALLBACK_URL, json=CALLBACK_BODY).status_code == 404
