import asyncio
import uuid
import pytest

from app.core import security

PW = "Passw0rd!"


def new_email():
    return f"{uuid.uuid4().hex[:12]}@test.com"


async def register(client, email=None, **over):
    body = {"email": email or new_email(), "full_name": "Ada Obi", "password": PW, **over}
    return await client.post("/auth/register", json=body)


async def test_register_creates_unverified_account_and_emails_a_token(client, outbox):
    email = new_email()
    r = await register(client, email)
    assert r.status_code == 201

    body = r.json()
    assert body["email"] == email and body["role"] == "complainant"
    assert body["is_verified"] is False
    assert "password" not in body and "password_hash" not in body

    await asyncio.sleep(0.05)  # Wait for background task
    assert [e for e, _ in outbox] == [email]


async def test_duplicate_email_is_rejected_case_insensitively(client, outbox):
    email = new_email()
    assert (await register(client, email)).status_code == 201
    assert (await register(client, email.upper())).status_code == 409


async def test_register_validation(client, outbox):
    assert (await register(client, password="abcdefgh")).status_code == 422
    assert (await register(client, password="Sh0rt!")).status_code == 422
    assert (await register(client, email="not-an-email")).status_code == 422
    assert (await register(client, full_name="A")).status_code == 422


async def test_email_verification_flow(client, outbox):
    email = new_email()
    await register(client, email)
    await asyncio.sleep(0.05)

    token = outbox[0][1]
    r = await client.get("/auth/verify-email", params={"token": token})
    assert r.status_code == 200 and r.json()["is_verified"] is True


async def test_bad_verification_tokens_are_401_not_500(client):
    assert (await client.get("/auth/verify-email", params={"token": "favour"})).status_code == 401

    # Create a token of the wrong type (e.g., access token instead of verify)
    wrong_type = security.create_access_token(1, token_version=0)
    assert (await client.get("/auth/verify-email", params={"token": wrong_type})).status_code == 401


async def test_login_returns_working_tokens(client, make_user):
    u = await make_user()

    r = await client.post("/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200
    tokens = r.json()
    assert tokens["token_type"] == "bearer"

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == u.email


async def test_login_failures_look_identical(client, make_user):
    u = await make_user()

    wrong = await client.post("/auth/login", json={"email": u.email, "password": "Wrong-pass1!"})
    unknown = await client.post("/auth/login", json={"email": new_email(), "password": PW})

    for r in (wrong, unknown):
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"
        assert r.json() == {"detail": "Incorrect email or password"}


async def test_login_is_case_insensitive_on_email(client, make_user):
    u = await make_user()
    r = await client.post("/auth/login", json={"email": u.email.upper(), "password": u.password})
    assert r.status_code == 200


async def test_deactivated_user_cannot_login(client, make_user):
    u = await make_user(active=False)
    r = await client.post("/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 401


async def test_deactivating_a_user_kills_their_existing_token(client, make_user):
    admin = await make_user("admin")
    u = await make_user()

    assert (await client.get("/auth/me", headers=u.headers)).status_code == 200

    r = await client.patch(f"/admin/users/{u.id}", json={"is_active": False}, headers=admin.headers)
    assert r.status_code == 200

    assert (await client.get("/auth/me", headers=u.headers)).status_code == 401


async def test_unverified_user_can_login_but_not_file_tickets(client, make_user, org):
    u = await make_user(verified=False)

    # Can login
    assert (await client.post("/auth/login", json={"email": u.email, "password": u.password})).status_code == 200

    # Cannot file a ticket
    r = await client.post(
        "/tickets",
        json={"title": "Leaking roof", "description": "Water drips in room 4.", "category_id": 1},
        headers=u.headers
    )
    assert r.status_code == 403


async def test_me_requires_a_valid_token(client):
    assert (await client.get("/auth/me")).status_code == 401
    r = await client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


async def test_refresh_flow_and_token_type_separation(client, make_user):
    u = await make_user()
    tokens = (await client.post("/auth/login", json={"email": u.email, "password": u.password})).json()

    # Refresh works
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200 and r.json()["access_token"]

    # An access token is not a refresh token
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401

    # A refresh token is not an access token
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401


async def test_resend_verification_does_not_reveal_which_emails_exist(client, make_user, outbox):
    email = new_email()
    await register(client, email)
    await asyncio.sleep(0.05)
    outbox.clear()

    known = await client.post("/auth/resend-verification", json={"email": email})
    unknown = await client.post("/auth/resend-verification", json={"email": new_email()})

    await asyncio.sleep(0.05)

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [e for e, _ in outbox] == [email]  # Only the real, unverified account got mail

    verified = await make_user()
    outbox.clear()

    await client.post("/auth/resend-verification", json={"email": verified.email})
    await asyncio.sleep(0.05)
    assert outbox == []


async def test_swagger_form_login(client, make_user):
    u = await make_user()

    # Valid form data
    ok = await client.post("/auth/token", data={"username": u.email, "password": u.password})
    assert ok.status_code == 200 and ok.json()["access_token"]

    # Invalid form data
    bad = await client.post("/auth/token", data={"username": "string", "password": "string"})
    assert bad.status_code == 401