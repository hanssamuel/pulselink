import random
import time

from tests.conftest import register, login, auth_headers

from app.db.session import SessionLocal
from app.models.ekg import EKGSample, EKGAnalysis


def _make_token(client, email):
    reg = register(client, email).json()
    return reg["access_token"], reg["user"]["id"]


def _ingest_synthetic(client, user_id, beat_times, window=10, hz=100, spike_mv=1.0):
    """Insert a baseline-noise signal with triangular R spikes at beat_times.

    beat_times are seconds from the start of the window; returns the absolute
    timestamps of the beats.
    """
    rng = random.Random(42)
    start = time.time() - window
    db = SessionLocal()
    try:
        n = int(window * hz)
        for i in range(n):
            t = i / hz
            mv = rng.uniform(-0.01, 0.01)
            for bt in beat_times:
                dt = abs(t - bt)
                if dt < 0.02:  # 20 ms half-width triangle
                    mv += spike_mv * (1.0 - dt / 0.02)
            db.add(EKGSample(patient_id=user_id, ts=start + t, mv=mv))
        db.commit()
    finally:
        db.close()
    return [start + bt for bt in beat_times]


def _analyze(client, token, seconds=10):
    return client.post(
        "/ekg/analysis",
        json={"seconds": seconds},
        headers=auth_headers(token),
    )


def test_heart_rate_detected_at_60bpm(client):
    token, user_id = _make_token(client, "hr60@example.com")
    _ingest_synthetic(client, user_id, [t + 0.5 for t in range(10)])

    r = _analyze(client, token)
    assert r.status_code == 200
    body = r.json()
    assert abs(body["heart_rate_bpm"] - 60.0) < 2.0
    assert body["flags"] == []
    assert body["sample_count"] >= 990  # a few ms of insert latency may trim the window edge


def test_rmssd_math_on_irregular_beats(client):
    token, user_id = _make_token(client, "rmssd@example.com")
    # alternating 0.8 s / 1.2 s RR intervals: mean RR = 1.0 s (60 bpm),
    # successive diffs are +/-0.4 s -> RMSSD = 400 ms exactly
    beats = [0.5]
    for k in range(9):
        beats.append(beats[-1] + (0.8 if k % 2 == 0 else 1.2))
    _ingest_synthetic(client, user_id, beats)

    body = _analyze(client, token).json()
    assert abs(body["heart_rate_bpm"] - 60.0) < 2.0
    assert abs(body["hrv_rmssd_ms"] - 400.0) < 10.0
    assert "irregular_rhythm" in body["flags"]


def test_tachycardia_flag(client):
    token, user_id = _make_token(client, "tachy@example.com")
    _ingest_synthetic(client, user_id, [0.5 + 0.5 * k for k in range(19)])  # 120 bpm

    body = _analyze(client, token).json()
    assert abs(body["heart_rate_bpm"] - 120.0) < 3.0
    assert body["flags"] == ["tachycardia"]


def test_bradycardia_flag(client):
    token, user_id = _make_token(client, "brady@example.com")
    _ingest_synthetic(client, user_id, [0.5 + 1.5 * k for k in range(6)])  # 40 bpm

    body = _analyze(client, token).json()
    assert abs(body["heart_rate_bpm"] - 40.0) < 2.0
    assert body["flags"] == ["bradycardia"]


def test_analysis_persisted(client):
    token, user_id = _make_token(client, "persist@example.com")
    _ingest_synthetic(client, user_id, [t + 0.5 for t in range(10)])

    body = _analyze(client, token).json()
    assert "id" in body
    row = SessionLocal().query(EKGAnalysis).filter_by(patient_id=user_id).one()
    assert row.id == body["id"]
    assert row.sample_count == body["sample_count"]
    assert abs(row.heart_rate_bpm - body["heart_rate_bpm"]) < 0.01
    assert abs(row.hrv_rmssd_ms - body["hrv_rmssd_ms"]) < 0.01
    assert row.flags == body["flags"]


def test_422_when_no_samples(client):
    token, _ = _make_token(client, "empty@example.com")
    r = _analyze(client, token)
    assert r.status_code == 422


def test_422_when_no_detectable_peaks(client):
    token, user_id = _make_token(client, "flat@example.com")
    rng = random.Random(7)
    db = SessionLocal()
    start = time.time() - 10
    try:
        for i in range(1000):
            db.add(EKGSample(patient_id=user_id, ts=start + i / 100, mv=rng.uniform(-0.01, 0.01)))
        db.commit()
    finally:
        db.close()

    r = _analyze(client, token)
    assert r.status_code == 422
    assert "heartbeats" in r.json()["detail"] or "samples" in r.json()["detail"]


def test_analysis_requires_auth(client):
    r = client.post("/ekg/analysis", json={"seconds": 10})
    assert r.status_code == 401


def test_seconds_out_of_range_rejected(client):
    token, user_id = _make_token(client, "range@example.com")
    _ingest_synthetic(client, user_id, [t + 0.5 for t in range(10)])
    for bad in (0, 301):
        r = client.post(
            "/ekg/analysis",
            json={"seconds": bad},
            headers=auth_headers(token),
        )
        assert r.status_code == 422, bad
