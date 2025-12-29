from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
from app.models.audit import AuditLog  # noqa: F401
 
