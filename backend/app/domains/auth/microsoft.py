import msal

from app.core.config import settings

SCOPES = ["User.Read"]


def _app() -> msal.ConfidentialClientApplication:
    # "organizations" accepts any work/school tenant; allowed_tenant_ids() narrows it.
    return msal.ConfidentialClientApplication(
        settings.MS_CLIENT_ID,
        authority="https://login.microsoftonline.com/organizations",
        client_credential=settings.MS_CLIENT_SECRET,
    )


def allowed_tenant_ids() -> set[str]:
    """Tenants allowed to sign in: MS_ALLOWED_TENANT_IDS, else just MS_TENANT_ID."""
    configured = {t.strip().lower() for t in settings.MS_ALLOWED_TENANT_IDS.split(",") if t.strip()}
    if configured:
        return configured
    return {settings.MS_TENANT_ID.strip().lower()} - {""}


def start_flow() -> dict:
    """Begin the auth-code flow (PKCE, state and nonce handled by MSAL)."""
    return _app().initiate_auth_code_flow(SCOPES, redirect_uri=settings.MS_REDIRECT_URI)


def email_from_callback(flow: dict, auth_response: dict) -> str:
    """Exchange the code, validate the id_token and return the user's email.

    Raises ValueError if the token is invalid or its tenant is not allowed.
    """
    result = _app().acquire_token_by_auth_code_flow(flow, auth_response)
    claims = result.get("id_token_claims")
    if not claims:
        raise ValueError(result.get("error_description", "Microsoft sign-in failed"))
    # Any Entra tenant can issue a valid token for a multi-tenant app, so the tenant
    # must be checked here or a foreign tenant could present one of our emails.
    if str(claims.get("tid", "")).lower() not in allowed_tenant_ids():
        raise ValueError("Microsoft tenant is not allowed")
    return (claims.get("preferred_username") or claims.get("email") or "").lower()
