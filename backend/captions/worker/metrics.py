"""In-memory latency metrics and API usage metering."""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict, deque

from sqlalchemy import text

from .. import db

log = logging.getLogger(__name__)


class Rolling:
    """Last N samples; reports p50/p95 for the dashboard."""

    def __init__(self, size: int = 200) -> None:
        self.values: deque[float] = deque(maxlen=size)

    def add(self, v: float) -> None:
        self.values.append(v)

    def summary(self) -> dict[str, float | int | None]:
        if not self.values:
            return {"p50": None, "p95": None, "n": 0}
        ordered = sorted(self.values)
        n = len(ordered)
        return {
            "p50": round(ordered[n // 2], 1),
            "p95": round(ordered[min(n - 1, int(n * 0.95))], 1),
            "n": n,
        }


class CampusMetrics:
    def __init__(self) -> None:
        self.stt_partial_ms = Rolling()
        self.stt_final_ms = Rolling()
        self.translate_ms: dict[str, Rolling] = defaultdict(Rolling)
        self.end_to_end_ms: dict[str, Rolling] = defaultdict(Rolling)

    def snapshot(self) -> dict:
        return {
            "stt_partial_ms": self.stt_partial_ms.summary(),
            "stt_final_ms": self.stt_final_ms.summary(),
            "translate_ms": {k: v.summary() for k, v in self.translate_ms.items()},
            "end_to_end_ms": {k: v.summary() for k, v in self.end_to_end_ms.items()},
        }


class UsageMeter:
    """Accumulates billable usage and flushes hourly buckets to PostgreSQL."""

    def __init__(self) -> None:
        self.pending: dict[tuple[dt.datetime, int, str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])

    @staticmethod
    def _hour(now: dt.datetime | None = None) -> dt.datetime:
        now = now or dt.datetime.now(dt.timezone.utc)
        return now.replace(minute=0, second=0, microsecond=0)

    def add(self, campus_id: int, provider: str, metric: str, quantity: float, cost: float, language: str = "") -> None:
        bucket = self.pending[(self._hour(), campus_id, provider, metric, language)]
        bucket[0] += quantity
        bucket[1] += cost

    async def flush(self) -> None:
        if not self.pending:
            return
        items, self.pending = self.pending, defaultdict(lambda: [0.0, 0.0])
        stmt = text(
            """
            INSERT INTO usage_records (period_start, campus_id, provider, metric, language, quantity, est_cost_usd)
            VALUES (:p, :c, :prov, :m, :l, :q, :cost)
            ON CONFLICT (period_start, campus_id, provider, metric, language)
            DO UPDATE SET quantity = usage_records.quantity + EXCLUDED.quantity,
                          est_cost_usd = usage_records.est_cost_usd + EXCLUDED.est_cost_usd
            """
        )
        try:
            async with db.sessionmaker()() as s:
                for (p, c, prov, metric, lang), (q, cost) in items.items():
                    await s.execute(stmt, {"p": p, "c": c, "prov": prov, "m": metric, "l": lang, "q": q, "cost": cost})
                await s.commit()
        except Exception:
            log.exception("usage flush failed; will retry")
            for key, (q, cost) in items.items():
                b = self.pending[key]
                b[0] += q
                b[1] += cost
