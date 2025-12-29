# PulseLink API

A backend API for ingesting and qreading of EKG signal data in near-real time.

Built with FastAPI and PostgreSQL.  
Designed to demonstrate secure ingestion, data integrity, and time-based querying.


## What this does

- Authenticates users with JWT
- Accepts EKG samples (timestamp + millivolts)
- Prevents duplicate signal inserts
- Returns recent signal data by time window
- Logs every request for auditing

This project focuses on backend correctness, not UI.


## Tech Stack

- FastAPI
- PostgreSQL
- SQLAlchemy
- JWT (stateless auth)
- Docker / Docker Compose


## Run the project

```bash
docker compose up -d --build
````

API runs at:

```
http://127.0.0.1:8001
```

---

## Quick walkthrough

### Register (one time)

```bash
curl -X POST http://127.0.0.1:8001/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "Osaslaycode@edo.com",
    "password": "Jollofand2",
    "role": "patient"
  }'
```

# Login and export token

```bash
export TOKEN="$(curl -s -X POST http://127.0.0.1:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"Osaslaycode@edo.com","password":"Jollofand2"}' \
| python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")"
```



# Ingest EKG samples

```bash
curl -X POST http://127.0.0.1:8001/ekg/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "samples": [
      { "ts": 1700000000.1, "mv": 0.12 },
      { "ts": 1700000000.2, "mv": 0.18 }
    ]
  }'
```

**Notes**

* Duplicate samples (same patient + timestamp) are ignored
* Enforced at the database level

---

# Query recent data

```bash
curl "http://127.0.0.1:8001/ekg/latest?seconds=60" \
  -H "Authorization: Bearer $TOKEN"
```

Example response:

```json
{
  "patient_id": 1,
  "seconds": 60,
  "count": 3,
  "samples": [
    { "ts": 1766708149.90, "mv": 0.12 },
    { "ts": 1766708149.91, "mv": 0.18 },
    { "ts": 1766708149.92, "mv": 0.05 }
  ]
}
```


# Audit logging

Every request is written to `audit_log` with:

* User ID (if authenticated)
* HTTP method
* Request path
* IP address
* Timestamp

Used for traceability and debugging.


# Design decisions & tradeoffs

* **JWT instead of sessions**
  Stateless and scalable. Easier to reason about in distributed systems.

* **Database-level deduplication**
  Unique constraint on `(patient_id, ts)` prevents race conditions.

* **Time-window queries**
  Matches how real signal data is consumed (recent history).

* **Simple role model**
  Keeps auth readable while remaining extensible.

* **No frontend**
  Intentional. Keeps scope focused on backend quality.



# Possible improvements

* Rate limiting on ingestion
* Signal validation (range, sampling rate)
* Pagination / cursor support
* WebSocket streaming for live signals
* Frontend visualization dashboard

---

## Author

Osayemwenre Jegbefumwen
Backend • Systems • Security-focused development
