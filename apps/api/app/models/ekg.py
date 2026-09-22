from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, Index, JSON
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


class EKGAnalysis(Base):
    """Persisted result of one POST /ekg/analysis run over a sample window."""

    __tablename__ = "ekg_analyses"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    window_start_ts = Column(Float, nullable=False)
    window_end_ts = Column(Float, nullable=False)
    sample_count = Column(Integer, nullable=False)

    heart_rate_bpm = Column(Float, nullable=False)
    hrv_rmssd_ms = Column(Float, nullable=False)

    # list of flag names, e.g. ["tachycardia", "irregular_rhythm"]
    flags = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

Index("ix_ekg_analysis_patient_created", EKGAnalysis.patient_id, EKGAnalysis.created_at)
