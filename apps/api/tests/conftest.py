import os
import tempfile

# Must be set before `app` (and therefore app.core.config.settings) is
# imported, since pydantic-settings reads the environment at import time.
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db_path}")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient

from app.core.limiter import limiter
from app.db.base import Base
from app.db.session import engine
from app.main import app


@pytest.fixture(autouse=True)
def _reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # TestClient always presents the same fake IP, so without this the
    # rate limiter would carry state across otherwise-independent tests.
    limiter.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def register(client, email, password="longenoughpw", **extra):
    return client.post("/auth/register", json={"email": email, "password": password, **extra})


def login(client, email, password="longenoughpw"):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}
