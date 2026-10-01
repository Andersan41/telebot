"""
scheduler/audit_resolver.py — Разрешение теневых outcome в signal_audit_log.

Blocked pipeline candidates with a full plan (hyp_entry/hyp_sl/hyp_tp +
synthetic_plan=True, см. scanner._hyp_plan) — гипотетические сделки.
Resolver периодически берёт неразрешённые строки, скачивает OHLCV после
ts_event и симулирует first-touch (SL-приоритет внутри бара, как в
scripts/virtual_outcomes.py), заполняя outcome/outcome_r/mae_r/mfe_r.

Это основа A/B-анализа порогов (min_p_tp 30% vs 50% и т.п.): без
разрешённых outcome теневые кандидаты нечем сравнивать.

Семантика outcome (единая с signal_outcomes):
  HIT_TP / HIT_SL / EXPIRED.
R-множители: outcome_r >= 0 для TP, -1.0 для SL; mae_r <= 0 <= mfe_r
(относительно |entry - sl|).

Env:
  AUDIT_RESOLVER_ENABLED=true
  AUDIT_RESOLVER_INTERVAL_SECONDS=1800   (30 мин)
  AUDIT_RESOLVER_BATCH=300               (строк за цикл)
  AUDIT_RESOLVER_MAX_AGE_DAYS=14         (старше — не берём)
  AUDIT_RESOLVER_EXPIRE_DAYS=7           (нет касания за 7 дней → EXPIRED)
"""
from __future__ import annotations

import asyncio
import math
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger

from data.exchange_client import exchange_client
from storage.database import db

AUDIT_RESOLVER_ENABLED = os.getenv("AUDIT_RESOLVER_ENABLED", "true").lower() == "true"
AUDIT_RESOLVER_INTERVAL_SECONDS = int(os.getenv("AUDIT_RESOLVER_INTERVAL_SECONDS", "1800"))
AUDIT_RESOLVER_BATCH = int(os.getenv("AUDIT_RESOLVER_BATCH", "1000"))
AUDIT_RESOLVER_MAX_AGE_DAYS = int(os.getenv("AUDIT_RESOLVER_MAX_AGE_DAYS", "14"))
AUDIT_RESOLVER_EXPIRE_DAYS = int(os.getenv("AUDIT_RESOLVER_EXPIRE_DAYS", "7"))

_TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
               "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440}


def _r_multiple(direction: str, entry: float, price: float, risk: float) -> float:
    """Signed move from entry in R (positive = favorable for the direction)."""
    if direction == "buy":
        return (price - entry) / risk
    return (entry - price) / risk


def simulate_outcome(
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    ts_event: datetime,
    bars: list[tuple[datetime, float, float, float]],
    now: datetime,
) -> Optional[tuple[str, float, float, float]]:
    """First-touch simulation after the entry bar.

    bars: (open_time, high, low, close) sorted ascending.
    Conservative SL priority inside a bar (unknown intra-bar ordering).
    Entry bar (open_time <= ts_event) is skipped — mirrors outcome_tracker.

    Returns (outcome, outcome_r, mae_r, mfe_r) or None if not yet resolvable.
    """
    if not entry or not sl or not tp:
        return None
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    direction = (direction or "").lower()
    if direction not in ("buy", "sell"):
        return None

    mae_r = 0.0
    mfe_r = 0.0
    last_close: Optional[float] = None
    saw_bar_after_entry = False

    for open_time, high, low, close in bars:
        if open_time <= ts_event:
            continue  # entry bar — skip (wick may predate the signal)
        saw_bar_after_entry = True
        fav = _r_multiple(direction, entry, high if direction == "buy" else low, risk)
        adv = _r_multiple(direction, entry, low if direction == "buy" else high, risk)
        mfe_r = max(mfe_r, fav)
        mae_r = min(mae_r, adv)
        last_close = close

        if direction == "buy":
            if low <= sl:
                return "HIT_SL", -1.0, mae_r, mfe_r
            if high >= tp:
                return "HIT_TP", _r_multiple(direction, entry, tp, risk), mae_r, mfe_r
        else:
            if high >= sl:
                return "HIT_SL", -1.0, mae_r, mfe_r
            if low <= tp:
                return "HIT_TP", _r_multiple(direction, entry, tp, risk), mae_r, mfe_r

    if not saw_bar_after_entry or last_close is None:
        return None  # данные ещё не покрывают период после входа
    if now - ts_event > timedelta(days=AUDIT_RESOLVER_EXPIRE_DAYS):
        return "EXPIRED", _r_multiple(direction, entry, last_close, risk), mae_r, mfe_r
    return None  # нет касания, но окна экспирации ещё не прошло


async def _resolve_group(
    rows: list,
    bars_by_key: dict[tuple[str, str], list],
) -> int:
    resolved = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        bars = bars_by_key.get((row.symbol, row.timeframe))
        if bars is None:
            continue
        result = simulate_outcome(
            direction=row.direction or "",
            entry=row.hypothetical_entry,
            sl=row.hypothetical_sl,
            tp=row.hypothetical_tp,
            ts_event=row.ts_event if row.ts_event.tzinfo else row.ts_event.replace(tzinfo=timezone.utc),
            bars=bars,
            now=now,
        )
        if result is None:
            continue
        outcome, outcome_r, mae_r, mfe_r = result
        try:
            await db.update_audit_outcome(
                row.id, outcome, round(outcome_r, 4),
                mae_r=round(mae_r, 4), mfe_r=round(mfe_r, 4),
            )
            resolved += 1
        except Exception as e:
            logger.warning(f"[AUDIT_RESOLVER] update failed id={row.id}: {e}")
    return resolved


async def resolve_audit_outcomes() -> int:
    """One resolver pass. Returns number of rows resolved."""
    if exchange_client._exchange is None or exchange_client._semaphore is None:
        logger.debug("[AUDIT_RESOLVER] exchange not connected yet — skipping pass")
        return 0
    rows = await db.get_unresolved_audits(
        limit=AUDIT_RESOLVER_BATCH,
        max_age_days=AUDIT_RESOLVER_MAX_AGE_DAYS,
    )
    if not rows:
        return 0

    groups: dict[tuple[str, str], list] = {}
    for row in rows:
        if not row.hypothetical_entry or not row.hypothetical_sl or not row.hypothetical_tp:
            continue
        if not row.direction:
            continue
        groups.setdefault((row.symbol, row.timeframe), []).append(row)

    bars_by_key: dict[tuple[str, str], list] = {}
    for (symbol, timeframe), group in groups.items():
        tf_minutes = _TF_MINUTES.get(timeframe, 60)
        earliest = min(r.ts_event for r in group)
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)
        needed = math.ceil((datetime.now(timezone.utc) - earliest).total_seconds() / 60 / tf_minutes) + 10
        limit = min(max(needed, 50), 2000)
        try:
            if limit > 900:
                # биржевой лимит ~1000/запрос — пагинация назад от "сейчас"
                df = await exchange_client.fetch_ohlcv_paginated(symbol, timeframe, total_limit=limit)
            else:
                df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            logger.warning(f"[AUDIT_RESOLVER] fetch failed {symbol} {timeframe}: {e}")
            continue
        if df is None or len(df) == 0:
            continue
        bars = [
            (idx if idx.tzinfo else idx.replace(tzinfo=timezone.utc),
             float(r["high"]), float(r["low"]), float(r["close"]))
            for idx, r in df.iterrows()
        ]
        bars.sort(key=lambda b: b[0])
        bars_by_key[(symbol, timeframe)] = bars

    resolved = await _resolve_group(rows, bars_by_key)
    if resolved:
        logger.info(
            f"[AUDIT_RESOLVER] resolved {resolved}/{len(rows)} shadow outcomes "
            f"({len(groups)} symbol/tf fetches)"
        )
    return resolved


async def audit_resolver_loop() -> None:
    if not AUDIT_RESOLVER_ENABLED:
        logger.info("[AUDIT_RESOLVER] disabled")
        return
    # первый проход — сразу после старта (добирает бэклог)
    try:
        await asyncio.sleep(30)
        while True:
            try:
                await resolve_audit_outcomes()
            except Exception as e:
                logger.warning(f"[AUDIT_RESOLVER] cycle error: {e}")
            await asyncio.sleep(AUDIT_RESOLVER_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        # tests/test_main.py патчит asyncio.sleep чтобы остановить главный
        # цикл main() — задача-консьюмер не должна печатать это как падение
        logger.debug("[AUDIT_RESOLVER] stopped")
