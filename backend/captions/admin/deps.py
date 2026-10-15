from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import db as dbmod
from .. import rkeys
from ..models import AuditLog

if TYPE_CHECKING:
    from .auth import AuthContext


async def get_db() -> AsyncIterator[AsyncSession]:
    async with dbmod.sessionmaker()() as session:
        yield session


def get_redis(request: Request):
    return request.app.state.redis


async def audit(db: AsyncSession, ctx: "AuthContext | None", action: str, target: str = "", ip: str | None = None, **details) -> None:
    db.add(
        AuditLog(
            user_id=ctx.user.id if ctx else None,
            username=ctx.user.username if ctx else "",
            action=action,
            target=target[:200],
            details=details,
            ip=ip,
        )
    )
    await db.commit()


async def config_changed(redis) -> None:
    """Tell the worker to reload configuration now instead of within 30 s."""
    await redis.publish(rkeys.CONFIG_CHANGED_CHANNEL, "1")
