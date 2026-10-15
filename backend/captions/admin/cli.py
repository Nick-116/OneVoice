"""Admin bootstrap CLI.

    docker compose run --rm admin python -m captions.admin.cli create-user --username alice --role admin
    docker compose run --rm admin python -m captions.admin.cli reset-mfa --username alice
    docker compose run --rm admin python -m captions.admin.cli set-password --username alice
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import delete, select

from .. import db
from ..models import AdminSession, AdminUser
from ..security import hash_password


def _prompt_password() -> str:
    while True:
        pw = getpass.getpass("Password (min 12 chars): ")
        if len(pw) < 12:
            print("Too short.")
            continue
        if pw != getpass.getpass("Repeat password: "):
            print("Passwords do not match.")
            continue
        return pw


async def create_user(username: str, role: str, display_name: str) -> None:
    async with db.sessionmaker()() as s:
        if (await s.execute(select(AdminUser).where(AdminUser.username == username))).scalar_one_or_none():
            sys.exit(f"User {username!r} already exists")
        s.add(AdminUser(username=username, role=role, display_name=display_name, password_hash=hash_password(_prompt_password())))
        await s.commit()
    print(f"Created {role} {username!r}. MFA enrolment will be required at first login.")


async def _with_user(username: str, fn) -> None:
    async with db.sessionmaker()() as s:
        user = (await s.execute(select(AdminUser).where(AdminUser.username == username))).scalar_one_or_none()
        if not user:
            sys.exit(f"No user {username!r}")
        fn(user)
        await s.execute(delete(AdminSession).where(AdminSession.user_id == user.id))
        await s.commit()


def main() -> None:
    p = argparse.ArgumentParser(prog="captions.admin.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("--username", required=True)
    c.add_argument("--role", choices=["admin", "operator"], default="admin")
    c.add_argument("--display-name", default="")
    r = sub.add_parser("reset-mfa")
    r.add_argument("--username", required=True)
    sp = sub.add_parser("set-password")
    sp.add_argument("--username", required=True)
    args = p.parse_args()

    async def run():
        try:
            if args.cmd == "create-user":
                await create_user(args.username, args.role, args.display_name)
            elif args.cmd == "reset-mfa":
                def reset(u):
                    u.mfa_enabled, u.totp_secret_enc = False, None
                await _with_user(args.username, reset)
                print("MFA reset; the user will enrol again at next login.")
            elif args.cmd == "set-password":
                pw = _prompt_password()
                await _with_user(args.username, lambda u: setattr(u, "password_hash", hash_password(pw)))
                print("Password updated; existing sessions signed out.")
        finally:
            await db.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
