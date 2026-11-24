"""
Encrypt every two-step secret that is still stored in clear and re-encrypt any made under the previous key.

    python -m app.scripts.encrypt_two_step_secrets

The API does the same at every start, so this is only needed to do it by hand (for example straight after a key
rotation). It is safe to run twice. It prints how many rows it changed and never a secret.
"""

from app.db import SessionLocal
from app.services import two_step_secrets


def main() -> int:
    db = SessionLocal()
    try:
        changed = two_step_secrets.encrypt_legacy(db)
    finally:
        db.close()
    print(f"Encrypted or re-encrypted {changed} two-step secret(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
