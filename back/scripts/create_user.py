"""Create or update a single local user account (see app/db/models/user.py,
app/services/local_auth.py).

Deliberately separate from scripts/seed.py: that script also inserts
example imx.* referential data (fake companies) meant only for local
dev/CI — safe there, wrong in production. This script touches only the
one user it's told to, so it's the one that's actually safe to run
against a real production database to create the first account.

Usage (inside the backend container):
    python -m scripts.create_user <username> <password>
"""
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.user import User
from app.services.password_hash import hash_password


def create_or_update_user(session: Session, username: str, password: str) -> None:
    """Idempotent: creates the account if it doesn't exist yet, otherwise
    resets its password — the same account-provisioning need either way."""
    user = session.scalar(select(User).where(User.username == username))
    if user is None:
        session.add(User(username=username, password_hash=hash_password(password)))
        print(f"Created user {username!r}.")
    else:
        user.password_hash = hash_password(password)
        print(f"Updated password for existing user {username!r}.")
    session.commit()


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.create_user <username> <password>")
        sys.exit(1)
    _, username, password = sys.argv

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    with Session(engine) as session:
        create_or_update_user(session, username, password)


if __name__ == "__main__":
    main()
