from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.schemas.user import UserRegister, UserLogin, UserResponse, TokenResponse

router  = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# I use HTTPBearer so FastAPI auto-generates the "Authorise" button in the OpenAPI UI,
# making it easier to test protected endpoints without a separate tool.
_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    # I include user identity, role and a short-lived expiration in the JWT payload.
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    # I factor this into a reusable dependency so any route can require an authenticated
    # user without duplicating the JWT decode + DB lookup logic.
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # I keep the role guard as a separate dependency so admin-only routes read cleanly:
    # `Depends(require_admin)` states the intent without embedding an if-block in every handler.
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return current_user


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    # I do a basic duplicate check to keep email unique until a proper DB constraint migration is added.
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        name          = payload.name,
        email         = payload.email,
        password_hash = hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    # The get_current_user dependency handles all decoding and DB lookup;
    # this handler just returns what was resolved.
    return current_user


@router.get("/users", response_model=list[UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 50,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # I name the admin dependency _admin (underscore prefix) to signal it is only used
    # for its side-effect (role guard), not its return value.
    return (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
