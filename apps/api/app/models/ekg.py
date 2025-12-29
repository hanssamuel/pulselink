from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, Index
from sqlalchemy.sql import func

from app.db.base import Base

class EKGSample(Base):
    __tablename__ = "ekg_samples"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # device timestamp (seconds since epoch) - optional but useful
    ts = Column(Float, nullable=False)

    # voltage / amplitude reading
    mv = Column(Float, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

# makes "latest N seconds for a patient" fast
Index("ix_ekg_patient_ts", EKGSample.patient_id, EKGSample.ts)
