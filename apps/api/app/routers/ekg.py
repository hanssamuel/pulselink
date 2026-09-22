from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
import time

from app.db.session import SessionLocal
from app.models.ekg import EKGSample, EKGAnalysis
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


# --- R-peak analysis -------------------------------------------------------
#
# Detection constants (documented so thresholds are auditable):
#   THRESHOLD_K        local maximum must exceed mean + k*std of the window
#   REFRACTORY_S       after accepting a peak, skip anything within 200 ms
#                      (physiologically two R-peaks cannot be closer, avoids
#                      double-counting a single QRS complex)
#   MIN_PEAKS          need >= 3 peaks (>= 2 RR intervals) for HR + RMSSD
#   TACHY_BPM / BRADY_BPM      flag thresholds for heart rate
#   IRREGULAR_CV       flag when std(RR)/mean(RR) > 0.15
#   IRREGULAR_RMSSD_MS flag when RMSSD of RR intervals > 100 ms

THRESHOLD_K = 2.5
REFRACTORY_S = 0.2
MIN_PEAKS = 3
TACHY_BPM = 100.0
BRADY_BPM = 60.0
IRREGULAR_CV = 0.15
IRREGULAR_RMSSD_MS = 100.0


class EKGAnalyze(BaseModel):
    seconds: int = Field(10, ge=1, le=300, description="analysis window length in seconds")


def _detect_r_peaks(tss, mvs):
    """Stdlib-only R-peak detector: thresholded local maxima + refractory period."""
    n = len(mvs)
    if n < 3:
        return []
    mean = sum(mvs) / n
    var = sum((v - mean) ** 2 for v in mvs) / n
    threshold = mean + THRESHOLD_K * (var ** 0.5)

    candidates = [
        i for i in range(1, n - 1)
        if mvs[i] > threshold and mvs[i] > mvs[i - 1] and mvs[i] >= mvs[i + 1]
    ]
    # strongest first, greedily accept while enforcing the refractory period
    candidates.sort(key=lambda i: mvs[i], reverse=True)
    accepted = []
    for i in candidates:
        if all(abs(tss[i] - tss[j]) >= REFRACTORY_S for j in accepted):
            accepted.append(i)
    return sorted(accepted)


@router.post("/analysis")
def analyze(payload: EKGAnalyze, db: Session = Depends(get_db), user=Depends(get_current_user)):
    now = time.time()
    window_start = now - payload.seconds

    rows = db.execute(
        select(EKGSample.ts, EKGSample.mv)
        .where(EKGSample.patient_id == user.id)
        .where(EKGSample.ts >= window_start)
        .order_by(EKGSample.ts.asc())
    ).all()

    if len(rows) < 3:
        raise HTTPException(status_code=422, detail="not enough samples in the requested window")

    tss = [r[0] for r in rows]
    mvs = [r[1] for r in rows]

    peak_idx = _detect_r_peaks(tss, mvs)
    if len(peak_idx) < MIN_PEAKS:
        raise HTTPException(
            status_code=422,
            detail=f"could not detect enough heartbeats in the window (found {len(peak_idx)}, need {MIN_PEAKS})",
        )

    peak_ts = [tss[i] for i in peak_idx]
    rr = [b - a for a, b in zip(peak_ts, peak_ts[1:])]  # RR intervals, seconds
    mean_rr = sum(rr) / len(rr)
    heart_rate_bpm = 60.0 / mean_rr

    succ_diffs = [b - a for a, b in zip(rr, rr[1:])]
    rmssd_s = (sum(d * d for d in succ_diffs) / len(succ_diffs)) ** 0.5
    rmssd_ms = rmssd_s * 1000.0

    var_rr = sum((x - mean_rr) ** 2 for x in rr) / len(rr)
    cv_rr = (var_rr ** 0.5) / mean_rr

    flags = []
    if heart_rate_bpm > TACHY_BPM:
        flags.append("tachycardia")
    elif heart_rate_bpm < BRADY_BPM:
        flags.append("bradycardia")
    if cv_rr > IRREGULAR_CV or rmssd_ms > IRREGULAR_RMSSD_MS:
        flags.append("irregular_rhythm")

    analysis = EKGAnalysis(
        patient_id=user.id,
        window_start_ts=window_start,
        window_end_ts=now,
        sample_count=len(rows),
        heart_rate_bpm=heart_rate_bpm,
        hrv_rmssd_ms=rmssd_ms,
        flags=flags,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    return {
        "id": analysis.id,
        "patient_id": user.id,
        "window_start_ts": window_start,
        "window_end_ts": now,
        "sample_count": len(rows),
        "heart_rate_bpm": round(heart_rate_bpm, 2),
        "hrv_rmssd_ms": round(rmssd_ms, 2),
        "flags": flags,
    }
