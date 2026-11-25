"""
Create the first administrator from a terminal.

Run it inside the API container or any shell that can reach the database:

    python -m app.scripts.create_admin

It asks for an email and a password. The password is typed without echo and is never
taken from an argument or printed. Registration is closed outside development, so this is
how the first admin comes to exist. It refuses an email that already has an account.
"""

import getpass
import sys

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User
from app.routes.auth import hash_password
from app.schemas.user import UserRegister
from app.services import audit_service


class AdminNotCreated(Exception):
    """The values were refused. The message says why and is safe to show."""


def create_admin(db: Session, email: str, password: str, name: str = "Administrator") -> User:
    # the same checks as POST /auth/register, so the rules cannot drift apart
    try:
        checked = UserRegister(name=name, email=email, password=password)
    except ValidationError as exc:
        reasons = "; ".join(str(err["msg"]).removeprefix("Value error, ") for err in exc.errors())
        raise AdminNotCreated(reasons) from None
    if db.query(User).filter(User.email == checked.email).first():
        raise AdminNotCreated("An account with that email already exists.")
    user = User(
        name=checked.name,
        email=checked.email,
        password_hash=hash_password(checked.password),
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # no request is involved, so the actor is the command itself
    audit_service.log_action(
        db,
        user_id="system",
        action="admin_created",
        resource="user",
        resource_id=str(user.id),
        detail="created with app.scripts.create_admin",
    )
    return user


def main() -> int:
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("The passwords do not match.", file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        # the address is read while the session is open: once it closes the saved user can no longer load it
        created = create_admin(db, email, password).email
    except AdminNotCreated as exc:
        print(f"Not created: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"Created admin {created}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
