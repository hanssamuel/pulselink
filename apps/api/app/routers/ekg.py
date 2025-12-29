from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
import time

from app.db.session import SessionLocal
from app.models.ekg import EKGSample
from app.routers.auth import get_current_user  # this must exist in your auth router

router = APIRouter(prefix="/ekg", tags=["ekg"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class EKGPoint(BaseModel):
    ts: float = Field(..., description="epoch seconds")
    mv: float = Field(..., description="millivolts")

class EKGIngest(BaseModel):
    samples: List[EKGPoint]

@router.post("/ingest")
def ingest(payload: EKGIngest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not payload.samples:
        raise HTTPException(status_code=400, detail="samples cannot be empty")

    rows = [{"patient_id": user.id, "ts": s.ts, "mv": s.mv} for s in payload.samples]

    stmt = (
        insert(EKGSample)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["patient_id", "ts"])
        .returning(EKGSample.id)
    )

    inserted_ids = db.execute(stmt).scalars().all()
    db.commit()

    return {"inserted": len(inserted_ids)}

@router.get("/latest")
def latest(seconds: int = 10, limit: int = 5000, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if seconds <= 0 or seconds > 300:
        raise HTTPException(status_code=400, detail="seconds must be 1..300")

    cutoff = time.time() - seconds

    stmt = (
        select(EKGSample.ts, EKGSample.mv)
        .where(EKGSample.patient_id == user.id)
        .where(EKGSample.ts >= cutoff)
        .order_by(EKGSample.ts.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).all()

    # return in ascending order for charting
    rows = list(reversed(rows))
    return {"patient_id": user.id, "seconds": seconds, "count": len(rows), "samples": [{"ts": r[0], "mv": r[1]} for r in rows]}
