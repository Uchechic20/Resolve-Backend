"""Create (or promote) an admin user. Needed once, because nobody can be
promoted to admin through the API until an admin exists.

Interactive:
    python -m app.scripts.create_admin --email admin@school.edu --name "Site Admin"

Non-interactive (CI, Docker): set ADMIN_PASSWORD in the environment.

Promote an account that already exists (e.g. you registered normally first):
    python -m app.scripts.create_admin --email me@school.edu --promote
"""
import argparse
import asyncio
import getpass
import os
import sys

from pydantic import ValidationError

from app.core import security
from app.core.database import SessionLocal, engine
from app.models import UserRole
from app.repositories import UserRepository
from app.schemas import UserRegister

current_dir=os.path.dirname(os.path.abspath(__file__))
project_root=os.path.abspath(os.path.join(current_dir,'..'))
if project_root not in sys.path:
    sys.path.insert(0,project_root)
def read_password() -> str:
    env = os.environ.get("ADMIN_PASSWORD")
    if env:
        return env
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return first


async def run(email: str, name: str | None, promote: bool) -> None:
    async with SessionLocal() as session:
        users = UserRepository(session)
        existing = await users.get_by_email(email)

        if existing:
            if not promote:
                sys.exit(f"{email} already exists. Re-run with --promote to make it an admin.")
            existing.role = UserRole.ADMIN
            existing.is_verified = True
            existing.is_active = True
            await session.commit()
            print(f"Promoted {email} to admin.")
            return

        if promote:
            sys.exit(f"No account for {email} to promote. Drop --promote to create one.")
        if not name:
            sys.exit("--name is required when creating a new admin.")

        try:
            data = UserRegister(email=email, full_name=name, password=read_password())
        except ValidationError as e:
            for err in e.errors():
                print(f"  {err['loc'][0]}: {err['msg']}", file=sys.stderr)
            sys.exit("Invalid input.")

        user = await users.create(
            email=data.email,
            password_hash=await security.hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.ADMIN,
        )
        user.is_verified = True  # no email round trip for the bootstrap admin
        await session.commit()
        print(f"Created admin {user.email} (id {user.id}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote a Resolve admin.")
    parser.add_argument("--name", required=False,default='super admin',help="Full name (required when creating)")
    parser.add_argument("--promote", action="store_true", help="Promote an existing account")
    parser.add_argument(
        "--email",
        required=False,
        default="admin@school.edu"
    )
    args = parser.parse_args()

    async def go():
        try:
            await run(args.email, args.name, args.promote)
        finally:
            await engine.dispose()

    asyncio.run(go())


if __name__ == "__main__":
    main()
