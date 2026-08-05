from fastapi import FastAPI, Request
from jose import jwt, JWTError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limiter import limiter
from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.models.audit import AuditLog
from app.routers.auth import router as auth_router
from app.routers.ekg import router as ekg_router


app = FastAPI(title="PulseLink API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.include_router(auth_router)
app.include_router(ekg_router)
def try_get_user_id(request: Request) -> int | None:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None

    token = auth.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except (JWTError, ValueError):
        return None


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    response = await call_next(request)

    user_id = try_get_user_id(request)
    ip = request.client.host if request.client else None

    db: Session = SessionLocal()
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                action=request.method,
                path=str(request.url.path),
                ip=ip,
            )
        )
        db.commit()
    finally:
        db.close()

    return response


@app.get("/health")
def health():
    return {"ok": True}


Base.metadata.create_all(bind=engine)
