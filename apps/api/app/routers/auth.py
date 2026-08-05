from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.core.config import settings
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

ADMIN_ASSIGNABLE_ROLES = {"patient", "caregiver", "creator", "admin"}


class RegisterIn(BaseModel):
    email: EmailStr
    password: str


class AdminCreateUserIn(BaseModel):
    email: EmailStr
    password: str
    role: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def _validate_password(password: str) -> None:
    # Password length guard (bcrypt max = 72 bytes)
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password must be 72 bytes or less")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")


@router.post("/register")
@limiter.limit("10/minute")
def register(request: Request, data: RegisterIn, db: Session = Depends(get_db)):
    """Public self-service signup. Always creates a 'patient' account --
    the only exception is bootstrapping the very first user in an empty
    database, who becomes 'admin' so there's a way to provision other
    roles at all. Anything beyond that requires an existing admin calling
    POST /auth/admin/users.
    """
    _validate_password(data.password)

    existing = db.scalar(select(User).where(User.email == data.email.lower()))
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    user_count = db.scalar(select(func.count()).select_from(User)) or 0
    role = "admin" if user_count == 0 else "patient"

    user = User(
        email=data.email.lower(),
        role=role,
        password_hash=hash_password(data.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(str(user.id))
    return {
        "access_token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
        },
    }


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Bad credentials")

    token = create_access_token(str(user.id))
    return {"access_token": token, "user": {"id": user.id, "email": user.email, "role": user.role}}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = auth.split(" ", 1)[1].strip()

    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        sub = payload.get("sub")
        user_id = int(sub) if sub is not None else None
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


@router.post("/admin/users", status_code=201)
@limiter.limit("10/minute")
def admin_create_user(
    request: Request,
    data: AdminCreateUserIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    _validate_password(data.password)

    role = data.role.strip().lower()
    if role not in ADMIN_ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.scalar(select(User).where(User.email == data.email.lower()))
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    user = User(
        email=data.email.lower(),
        role=role,
        password_hash=hash_password(data.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"id": user.id, "email": user.email, "role": user.role}
