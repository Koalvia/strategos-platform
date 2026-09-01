"""Create a local user that can actually log in.

Unlike ``seed_staff_users`` (which writes unusable password hashes on purpose), this
creates a verified account with a real password — what testing the visibility scope needs.

Run from ``backend/``::

    python -m scripts.create_user --name "Fatima" --email fatima@strategos.ad --password ...

The email is what ties the account to its Business Central resource (``resources.email``),
so it must match BC exactly for the customer scope to resolve.
"""

import argparse
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


def create_user(
    db: Session, name: str, email: str, password: str, role: str | None = None
) -> User:
    """Create a verified user, refusing to touch an existing account."""
    existing = db.query(User).filter(User.email.ilike(email)).one_or_none()
    if existing is not None:
        raise SystemExit(
            f"A user with email {email} already exists (id={existing.id}). "
            "Delete it first or pick another email — this script never overwrites."
        )

    user = User(
        name=name,
        email=email,
        role=role,
        hashed_password=get_password_hash(password),
        is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a verified local user")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default=None, help="Staff role for the Usuarios list")
    args = parser.parse_args()

    from app.db.session import get_db

    db = next(get_db())
    try:
        user = create_user(db, args.name, args.email, args.password, args.role)
        print(f"Created user {user.email} (id={user.id}, verified)")
        print(
            "It resolves against Business Central only if resources.email matches "
            f"{user.email} exactly."
        )
    except SystemExit:
        raise
    except Exception:
        print("Failed to create the user:")
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
