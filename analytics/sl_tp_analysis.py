"""
analytics/sl_tp_analysis.py — Анализ эффективности SL/TP по таймфреймам.

На основе реальных сделок определяет:
- Какие TF дают лучший винрейт
- Средний реальный PnL по TF
- Частоту срабатывания SL vs TP по TF
- Средний RR после закрытия
- Рекомендации по корректировке ATR multiplier

Usage:
    python -m analytics.sl_tp_analysis [--min-trades 5]
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.database import db, Signal, SignalOutcome
from sqlalchemy import select, desc


async def analyze_sl_tp(min_trades: int = 3) -> dict:
    """Analyze SL/TP effectiveness by timeframe."""
    async with db._session_factory() as session:
        result = await session.execute(
            select(SignalOutcome, Signal)
            .join(Signal, SignalOutcome.signal_id == Signal.id)
            .where(SignalOutcome.status != "OPEN")
            .order_by(SignalOutcome.closed_at.desc())
        )
        closed = [(outcome, signal) for outcome, signal in result.all()]

    if not closed:
        return {"error": "No closed trades yet", "recommendations": []}

    # Group by TF
    tf_data: dict[str, list] = defaultdict(list)
    for outcome, signal in closed:
        tf_data[signal.timeframe].append({
            "symbol": signal.symbol,
            "direction": signal.signal_type,
            "entry": signal.close_price,
            "sl": signal.sl,
            "tp": signal.tp,
            "exit_price": outcome.close_price,
            "pnl_pct": outcome.pnl_pct,
            "status": outcome.status,
            "closed_at": outcome.closed_at,
        })

    analysis = {}
    recommendations = []

    for tf, trades in sorted(tf_data.items()):
        pnls = [t["pnl_pct"] for t in trades if t["pnl_pct"] is not None]
        if not pnls:
            continue

        total = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        wr = wins / total * 100 if total else 0
        avg_pnl = sum(pnls) / total if total else 0
        best = max(pnls)
        worst = min(pnls)

        # Profit factor
        gains = sum(p for p in pnls if p > 0)
        abs_losses = abs(sum(p for p in pnls if p < 0))
        pf = gains / abs_losses if abs_losses > 0 else (float("inf") if gains > 0 else 0)

        # SL hit rate
        sl_hits = sum(1 for t in trades if t["status"] == "HIT_SL")
        tp_hits = sum(1 for t in trades if t["status"] == "HIT_TP")
        sl_rate = sl_hits / total * 100 if total else 0

        # Average SL distance (as % of entry)
        sl_distances = []
        for t in trades:
            if t["sl"] and t["entry"] and t["entry"] > 0:
                dist = abs(t["sl"] - t["entry"]) / t["entry"] * 100
                sl_distances.append(dist)
        avg_sl_dist = sum(sl_distances) / len(sl_distances) if sl_distances else 0

        # Average TP distance (as % of entry)
        tp_distances = []
        for t in trades:
            if t["tp"] and t["entry"] and t["entry"] > 0:
                dist = abs(t["tp"] - t["entry"]) / t["entry"] * 100
                tp_distances.append(dist)
        avg_tp_dist = sum(tp_distances) / len(tp_distances) if tp_distances else 0

        # RR ratio (actual)
        rr_values = []
        for t in trades:
            if t["entry"] and t["sl"] and t["tp"]:
                sl_dist = abs(t["entry"] - t["sl"])
                tp_dist = abs(t["tp"] - t["entry"])
                if sl_dist > 0:
                    rr_values.append(tp_dist / sl_dist)
        avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0

        tf_analysis = {
            "total": total,
            "wins": wins,
            "losses": losses,
            "winrate": round(wr, 1),
            "avg_pnl": round(avg_pnl, 2),
            "best_pnl": round(best, 2),
            "worst_pnl": round(worst, 2),
            "profit_factor": round(pf, 2),
            "sl_hit_rate": round(sl_rate, 1),
            "avg_sl_distance_pct": round(avg_sl_dist, 3),
            "avg_tp_distance_pct": round(avg_tp_dist, 3),
            "avg_rr_ratio": round(avg_rr, 2),
        }
        analysis[tf] = tf_analysis

        # Generate recommendations
        if total >= min_trades:
            if sl_rate > 70:
                recommendations.append(
                    f"⚠️ {tf}: SL срабатывает в {sl_rate:.0f}% случаев — "
                    f"рассмотреть увеличение SL (сейчас ~{avg_sl_dist:.2f}%)"
                )
            if wr < 40:
                recommendations.append(
                    f"⚠️ {tf}: Винрейт {wr:.0f}% — "
                    f"нужна корректировка TP или фильтров"
                )
            if avg_rr < 1.5:
                recommendations.append(
                    f"⚠️ {tf}: Средний RR {avg_rr:.1f} — "
                    f"TP слишком далеко или SL слишком близко"
                )
            if wr >= 60 and pf >= 1.5:
                recommendations.append(
                    f"✅ {tf}: Хорошие показатели (WR={wr:.0f}%, PF={pf:.1f})"
                )

    if not recommendations:
        if sum(a["total"] for a in analysis.values()) < min_trades:
            recommendations.append(f"📊 Нужно минимум {min_trades} закрытых сделок для анализа")
        else:
            recommendations.append("📊 Показатели в норме, корректировка не требуется")

    return {
        "analysis": analysis,
        "recommendations": recommendations,
        "total_trades": sum(a["total"] for a in analysis.values()),
    }


def format_sl_tp_report(result: dict) -> str:
    """Format SL/TP analysis as readable text."""
    if "error" in result:
        return f"❌ {result['error']}"

    lines = ["📊 Анализ SL/TP по таймфреймам", ""]

    analysis = result["analysis"]
    for tf, data in sorted(analysis.items()):
        lines.append(f"═══ {tf} ═══")
        lines.append(f"  Сделок: {data['total']} (WIN: {data['wins']}, LOSS: {data['losses']})")
        lines.append(f"  Винрейт: {data['winrate']}%")
        lines.append(f"  Средний PnL: {data['avg_pnl']:+.2f}%")
        lines.append(f"  Лучшая/худшая: {data['best_pnl']:+.2f}% / {data['worst_pnl']:+.2f}%")
        lines.append(f"  Profit Factor: {data['profit_factor']}")
        lines.append(f"  SL hit rate: {data['sl_hit_rate']}%")
        lines.append(f"  Средний SL: ~{data['avg_sl_distance_pct']:.2f}% от entry")
        lines.append(f"  Средний TP: ~{data['avg_tp_distance_pct']:.2f}% от entry")
        lines.append(f"  Средний RR: 1:{data['avg_rr_ratio']}")
        lines.append("")

    lines.append("═══ Рекомендации ═══")
    for rec in result["recommendations"]:
        lines.append(f"  {rec}")

    return "\n".join(lines)


if __name__ == "__main__":
    result = asyncio.run(analyze_sl_tp())
    print(format_sl_tp_report(result))
