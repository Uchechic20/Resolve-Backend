
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

# 1. UPDATE ENVIRONMENT VARIABLES IMMEDIATELY
os.environ.update({
    "DATABASE_URL": "postgresql+asyncpg://unused:unused@localhost:5432/unused_test",
    "ENVIRONMENT": "testing",
    "BCRYPT_ROUNDS": "4",
    "LOG_LEVEL": "WARNING",
    "EMAIL_BACKEND": "smtp",
    "RATE_LIMIT_ENABLED": "false",
    "SECRET_KEY": "test-secret-key-that-is-long-enough-32",
})

# 2. NOW IMPORT APP MODULES
import pytest
import pytest_asyncio
from dotenv import dotenv_values
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base # <--- This is now safe

ROOT = Path(__file__).resolve().parent.parent
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or dotenv_values(ROOT / ".env").get("TEST_DATABASE_URL")

UPLOAD_DIR = tempfile.mkdtemp(prefix="resolve_test_uploads_")

# Must be set BEFORE any app modules are imported
os.environ.update({
    "DATABASE_URL": TEST_DB_URL or "postgresql+asyncpg://unused:unused@localhost:5432/unused_test",
    "ENVIRONMENT": "testing",
    "BCRYPT_ROUNDS": "4",
    "LOG_LEVEL": "WARNING",
    "EMAIL_BACKEND": "smtp",
    "RATE_LIMIT_ENABLED": "false",
    "UPLOAD_DIR": UPLOAD_DIR,
    "MAX_UPLOAD_MB": "1",
    "MAX_ATTACHMENTS_PER_TICKET": "5",
})

# Initialize the test engine
test_engine = create_async_engine(
    TEST_DB_URL or "postgresql+asyncpg://unused:unused@localhost:5432/unused_test",
    poolclass=NullPool,
)


def _db_ready() -> tuple[bool, str]:
    if not TEST_DB_URL:
        return False, "TEST_DATABASE_URL is not set (see tests/conftest.py)"

    # Extract database name from URL
    name = TEST_DB_URL.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith("_test"):
        return False, f"Refusing to run: database '{name}' does not end with '_test'. The API tests DROP ALL TABLES."
    return True, ""


DB_OK, DB_MSG = _db_ready()


def pytest_collection_modifyitems(config, items):
    """Skip (not fail) API tests when no safe test database is configured."""
    if DB_OK:
        return
    skip = pytest.mark.skip(reason=DB_MSG)
    for item in items:
        if "tests/api" in item.nodeid.replace("\\", "/"):
            item.add_marker(skip)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Create tables before the session, drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database():
    # The engine is already created globally, we just need to ensure tables exist
    # setup_database handles create_all/drop_all.
    yield


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(database):
    import httpx
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def outbox(monkeypatch):
    """Captures verification emails instead of sending them: [(email, token)]."""
    import app.routers.auth as auth_routes

    sent: list[tuple[str, str]] = []

    async def fake_send(email: str, token: str) -> None:
        sent.append((email, token))

    monkeypatch.setattr(auth_routes, "send_verification_email", fake_send)
    return sent


@dataclass
class Person:
    id: int
    email: str
    password: str
    role: str
    headers: dict = field(default_factory=dict)


@pytest_asyncio.fixture
async def make_user(database):
    """Create a user straight in the database and return a Person with a ready-to-use Authorization header."""
    from app.core import security
    from app.core.database import SessionLocal
    from app.models import UserRole
    from app.repositories import UserRepository

    async def _make(role: str = "complainant", verified: bool = True, active: bool = True, password: str = "Passw0rd!"):
        email = f"{uuid.uuid4().hex[:12]}@test.com"
        async with SessionLocal() as session:
            # Note: security.hash_password might be async depending on your implementation
            hashed_pw = security.hash_password(password)
            if hasattr(hashed_pw, "__await__"):
                hashed_pw = await hashed_pw

            user = await UserRepository(session).create(
                email=email,
                password_hash=hashed_pw,
                full_name="Test User",
                role=UserRole(role),
            )
            user.is_verified = verified
            user.is_active = active
            await session.commit()
            uid = user.id

        token = security.create_access_token(uid, token_version=0)
        return Person(uid, email, password, role, {"Authorization": f"Bearer {token}"})

    return _make


@pytest_asyncio.fixture
async def org(client, make_user):
    """A fresh organisation per test: admin, a department (head + 2 agents), an 'outsider' agent, and two complainants."""
    admin = await make_user("admin")
    head = await make_user("agent")
    a1 = await make_user("agent")
    a2 = await make_user("agent")
    outsider = await make_user("agent")
    c1 = await make_user("complainant")
    c2 = await make_user("complainant")

    async def post(path, body):
        r = await client.post(path, json=body, headers=admin.headers)
        assert r.status_code == 201, f"{path}: {r.status_code} {r.text}"
        return r.json()

    tag = uuid.uuid4().hex[:8]
    dept = await post("/admin/departments", {"name": f"Hostel-{tag}"})
    other = await post("/admin/departments", {"name": f"Academics-{tag}"})
    cat = await post("/admin/categories", {"name": f"Water-{tag}", "suggested_department_id": dept["id"]})

    for person, role in [(head, "head"), (a1, "agent"), (a2, "agent")]:
        await post(f"/admin/departments/{dept['id']}/members", {"user_id": person.id, "member_role": role})

    await post(f"/admin/departments/{other['id']}/members", {"user_id": outsider.id, "member_role": "agent"})

    return SimpleNamespace(
        admin=admin, head=head, a1=a1, a2=a2, outsider=outsider, c1=c1, c2=c2,
        dept_id=dept["id"], other_dept_id=other["id"], cat_id=cat["id"]
    )