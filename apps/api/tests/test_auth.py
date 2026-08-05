from tests.conftest import register, login, auth_headers


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_first_registration_becomes_admin(client):
    r = register(client, "first@example.com")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"


def test_second_registration_cannot_choose_role(client):
    register(client, "first@example.com")
    r = register(client, "second@example.com", role="admin")
    assert r.json()["user"]["role"] == "patient"


def test_password_too_short_rejected(client):
    r = register(client, "a@example.com", password="short")
    assert r.status_code == 400


def test_password_too_long_rejected(client):
    r = register(client, "a@example.com", password="x" * 100)
    assert r.status_code == 400


def test_duplicate_email_rejected(client):
    register(client, "dup@example.com")
    r = register(client, "dup@example.com")
    assert r.status_code == 409


def test_login_success(client):
    register(client, "a@example.com")
    r = login(client, "a@example.com")
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_bad_credentials(client):
    r = login(client, "nobody@example.com", "whatever1")
    assert r.status_code == 401


def test_admin_can_create_caregiver(client):
    admin = register(client, "admin@example.com").json()
    r = client.post(
        "/auth/admin/users",
        json={"email": "c@example.com", "password": "longenoughpw", "role": "caregiver"},
        headers=auth_headers(admin["access_token"]),
    )
    assert r.status_code == 201
    assert r.json()["role"] == "caregiver"


def test_non_admin_cannot_create_users(client):
    register(client, "admin@example.com")
    patient = register(client, "p@example.com").json()

    r = client.post(
        "/auth/admin/users",
        json={"email": "x@example.com", "password": "longenoughpw", "role": "admin"},
        headers=auth_headers(patient["access_token"]),
    )
    assert r.status_code == 403


def test_admin_rejects_invalid_role(client):
    admin = register(client, "admin@example.com").json()
    r = client.post(
        "/auth/admin/users",
        json={"email": "x@example.com", "password": "longenoughpw", "role": "superuser"},
        headers=auth_headers(admin["access_token"]),
    )
    assert r.status_code == 400


def test_login_rate_limited(client):
    register(client, "victim@example.com")

    last_status = None
    for _ in range(15):
        last_status = login(client, "victim@example.com", "wrong-password").status_code

    assert last_status == 429


def test_admin_create_requires_auth(client):
    register(client, "admin@example.com")
    r = client.post(
        "/auth/admin/users",
        json={"email": "x@example.com", "password": "longenoughpw", "role": "patient"},
    )
    assert r.status_code == 401
