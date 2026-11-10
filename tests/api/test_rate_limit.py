import uuid
import pytest


@pytest.fixture
def limiter_on():
    from app.core.rate_limit import limiter

    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()


async def test_login_is_limited_per_client(client, limiter_on):
    body = {"email": f"{uuid.uuid4().hex[:8]}@test.com", "password": "Wr0ng-pass!"}

    # Fire 12 requests
    codes = [(await client.post("/auth/login", json=body)).status_code for _ in range(12)]

    # The first 10 should be 401 (Unauthorized), the 11th and 12th should be 429 (Too Many Requests)
    assert codes[:10] == [401] * 10  # default: 10 per minute
    assert codes[10:] == [429, 429]


async def test_limit_response_is_clean_json(client, limiter_on):
    body = {"email": "nobody@test.com", "password": "Wr0ng-pass!"}

    # Exhaust the limit
    for _ in range(11):
        r = await client.post("/auth/login", json=body)

    assert r.status_code == 429
    assert "detail" in r.json()


async def test_registration_is_limited(client, limiter_on):
    def body():
        return {
            "email": f"{uuid.uuid4().hex[:10]}@test.com",
            "full_name": "Rate Test",
            "password": "Passw0rd!"
        }

    # Fire 6 registration requests
    codes = [(await client.post("/auth/register", json=body())).status_code for _ in range(6)]

    # The first 5 should be 201 (Created), the 6th should be 429
    assert codes == [201, 201, 201, 201, 201, 429]  # default: 5 per hour


async def test_unlimited_routes_are_unaffected(client, limiter_on):
    # Health check should not be rate-limited
    for _ in range(30):
        assert (await client.get("/health")).status_code == 200