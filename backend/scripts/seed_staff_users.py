"""Idempotent seed for the Strategos staff shown in the Usuarios directory.

These are display-only accounts: they carry a name, role and ``@estrategos.ad``
email (all non-sensitive display values) so the Usuarios page can render "who's
who". They are **not** intended to log in this round, so each row gets a random,
unusable ``hashed_password`` (a bcrypt hash of a throwaway secret nobody keeps) —
no real password or secret is ever committed.

Run it directly to seed a live database::

    python -m scripts.seed_staff_users        # from backend/

or import :func:`seed_staff_users` and call it with a session (the tests do this).
The operation is idempotent: matching an existing user by email updates its name
and role in place instead of inserting a duplicate.
"""

import secrets
import sys
import traceback
from pathlib import Path

# Add the backend directory to the path so ``app`` imports work when run directly.
script_dir = Path(__file__).parent
app_dir = script_dir.parent
sys.path.insert(0, str(app_dir))

from sqlalchemy.orm import Session  # noqa: E402

from app.domains.auth.models import User  # noqa: E402
from app.domains.auth.utils import get_password_hash  # noqa: E402

# (name, role, email) for the Strategos staff mirrored from the Usuarios mock.
STAFF: list[tuple[str, str, str]] = [
    ("Marc Solé", "Soci Director", "marc@estrategos.ad"),
    ("Anna Ferrer", "Responsable Fiscal", "anna@estrategos.ad"),
    ("Laura Puig", "Responsable Laboral", "laura@estrategos.ad"),
    ("Jordi Vila", "Tècnic Comptable", "jordi@estrategos.ad"),
    ("Núria Camps", "Tècnica Administrativa", "nuria@estrategos.ad"),
    ("Pol Ribas", "Administració", "pol@estrategos.ad"),
]


def _unusable_password_hash() -> str:
    """Return a valid bcrypt hash of a random secret nobody retains.

    The hash format is legitimate (so auth code paths never choke on it), but the
    underlying password is discarded, making the account impossible to log into.
    """
    return get_password_hash(secrets.token_urlsafe(32))


def seed_staff_users(db: Session) -> list[User]:
    """Create or update the Strategos staff users. Idempotent, keyed by email.

    Existing users (matched case-insensitively by email) have their name and role
    refreshed; their password is left untouched. New users are inserted with an
    unusable password hash. Returns the affected users in the mock's display order.
    """
    seeded: list[User] = []
    for name, role, email in STAFF:
        user = (
            db.query(User)
            .filter(User.email.ilike(email))
            .one_or_none()
        )
        if user is None:
            user = User(
                name=name,
                email=email,
                role=role,
                hashed_password=_unusable_password_hash(),
            )
            db.add(user)
        else:
            user.name = name
            user.role = role
        seeded.append(user)

    db.commit()
    for user in seeded:
        db.refresh(user)
    return seeded


def main() -> None:
    from app.db.session import get_db

    db = next(get_db())
    try:
        users = seed_staff_users(db)
        print(f"✅ Seeded {len(users)} staff users:")
        for user in users:
            print(f"  • {user.name} · {user.role} · {user.email}")
    except Exception:
        print("❌ Failed to seed staff users:")
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
