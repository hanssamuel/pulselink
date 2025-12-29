from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    role: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    # Password length guard (bcrypt max = 72 bytes)
    if len(data.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=400,
            detail="Password must be 72 bytes or less"
        )

    role = data.role.strip().lower()
    if role not in {"patient", "caregiver", "creator", "admin"}:
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
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Bad credentials")

    token = create_access_token(str(user.id))
    return {"access_token": token, "user": {"id": user.id, "email": user.email, "role": user.role}}

from fastapi import Depends, HTTPException, Request
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User


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

