# Resolve

Incident and complaint management API (FastAPI, async SQLAlchemy, PostgreSQL).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # then edit DATABASE_URL and SECRET_KEY
alembic upgrade head          # create the tables
python -m app.scripts.create_admin --email you@school.edu --name "Your Name"
uvicorn app.main:app --reload # docs at http://localhost:8000/docs
```

Behind a reverse proxy, add `--proxy-headers --forwarded-allow-ips="<proxy ip>"`
so rate limits apply per user instead of per proxy.

## Changing the schema

```bash
alembic revision --autogenerate -m "describe the change"
# Review the file. Autogenerate does NOT detect sequences or data changes.
alembic upgrade head
```

## Tests

135 tests: 68 unit tests (no database) and 67 API tests that drive the real
endpoints against PostgreSQL.

**One-time setup**
1. Create an empty database whose name ends in `_test`: `CREATE DATABASE resolve_test;`
2. Add this line to your `.env`:
   `TEST_DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@localhost:5432/resolve_test`

**Run** (terminal, project root, venv active)
```bash
pytest                    # everything
pytest tests/unit         # fast, no database needed
pytest tests/api/test_tickets.py -k reopen   # a single area
pytest -x -q              # stop at first failure, short output
```
In PyCharm: Settings > Tools > Python Integrated Tools > Default test runner =
pytest, then right-click the `tests` folder > Run 'pytest in tests'.

**Safety:** the API tests DROP AND RECREATE ALL TABLES in the test database.
They refuse to run unless the database name ends with `_test`, and are skipped
(not failed) when `TEST_DATABASE_URL` is missing. Unit tests always run.

| File | Covers |
|---|---|
| `tests/unit/test_state_machine.py` | every allowed/blocked status change |
| `tests/unit/test_security.py` | hashing, token types, expiry, tampering |
| `tests/unit/test_schemas.py` | request validation rules |
| `tests/unit/test_config.py` | startup safety checks for production |
| `tests/unit/test_attachment_helpers.py` | file-type sniffing, filename cleaning |
| `tests/api/test_auth.py` | register, verify, login, refresh, resend |
| `tests/api/test_tickets.py` | filing, visibility, lifecycle, triage, reopen |
| `tests/api/test_collaboration.py` | claim race, assign, transfer, internal notes, queues |
| `tests/api/test_admin.py` | departments, members, categories, users |
| `tests/api/test_attachments.py` | upload rules, downloads, deletes, limits |
| `tests/api/test_rate_limit.py` | limits trigger and clean 429 responses |

## Layout

```
app/
  core/          config, database, security, mailer, rate_limit, storage, log
  models/        SQLAlchemy tables
  schemas/       request/response shapes
  repositories/  database access only
  services/      business rules, permissions, transactions
  routers/       thin HTTP layer
  scripts/       create_admin
alembic/         migrations
tests/
```
