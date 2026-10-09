# Multi-tenant Microsoft SSO (Koalvia + STRATEGOS) — design

Date: 2026-10-09
Builds on: the Microsoft SSO login on branch `feat/microsoft-sso` (single-tenant, existing users only).

## Goal
Let staff with `@strategos.ad` accounts sign in with Microsoft SSO, as `@koalvia.com` accounts already do.

## Context and findings
- `strategos.ad` is its own Microsoft tenant (`e9cf8bf3-1d78-4f23-94f9-9a494d01dc4e`, "STRATEGOS"), different from Koalvia's (`f9b51fd2-8550-473d-ae84-9d4f9814e835`). Verified via the public `openid-configuration` and `getuserrealm` endpoints.
- The Entra app registration is currently "single tenant", so Microsoft rejects STRATEGOS accounts before they reach the backend.
- Manager vs employee already comes from Business Central (`resources.manageAllCustomers`, matched by email in `app/core/visibility.py`) and the UI already reflects what each sees. **Out of scope:** any change to roles or permissions (separate ticket).

## Decisions
- Sign-in stays "existing users only": the email must already exist in `users`. No auto-provisioning.
- Approach: multi-tenant app registration plus a backend allowlist of tenant IDs. (Rejected: inviting STRATEGOS staff as guests in Koalvia's tenant, which needs per-person invites and a different, less reliable email claim.)

## Design
1. **Azure (manual):** set "Supported account types" to "Accounts in any organizational directory (multitenant)". Do **not** allow personal Microsoft accounts. A STRATEGOS admin grants consent once. The redirect URIs do not change.
2. **Config (`app/core/config.py`, `.env.example`):**
   - `MS_TENANT_ID` is replaced as authority by `organizations` (`https://login.microsoftonline.com/organizations`).
   - New `MS_ALLOWED_TENANT_IDS: list[str] = []` (comma-separated in `.env`): Koalvia and STRATEGOS tenant IDs. Empty falls back to `MS_TENANT_ID` alone (so existing single-tenant setups keep working); if both are empty, no one can sign in. Stored as a comma-separated string.
3. **Backend (`app/domains/auth/microsoft.py`):** after MSAL validates the code and id_token, read the `tid` claim and raise `ValueError` if it is not in `MS_ALLOWED_TENANT_IDS`. The existing service maps that to 401. The email lookup (case-insensitive, existing users only) is unchanged.
4. **Why the allowlist is required:** with a multi-tenant app, any Entra tenant can issue a valid token. Without the `tid` check, a foreign tenant could present an email matching one of our users.
5. **No changes:** database schema (no migration), API endpoints, frontend routes and login page.

## Tests (`backend/tests/test_auth_microsoft.py`)
- Token from an allowed tenant, email in `users` → 200 and JWT (cover both tenant IDs).
- Token from a tenant not in the list, email in `users` → 401, no JWT.
- Empty allowlist → 401.
- Existing Koalvia cases keep passing (the mock in the tests supplies `tid`).
- The Microsoft wrapper returns the email and tenant, so the check is testable without network.

## Rollout
1. Update the Azure registration and get STRATEGOS admin consent.
2. Set `MS_ALLOWED_TENANT_IDS` and the new authority in `backend/.env`; restart `api`.
3. Make sure real `@strategos.ad` emails exist in `users` (local DB also has `@estrategos.ad` rows that will not match).
4. Test with one STRATEGOS account and one unlisted account.

## Consent
- `ma@strategos.ad` (the app's manager) is also a STRATEGOS Entra admin and grants the one-time consent.
