"""
Тестовое уведомление сигнала для NEAR/USDT в Telegram канал.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config.logger
from config.settings import config
from bot.notifier import send_signal
from strategy.signal_engine import SignalResult, SignalType
from context.scorer import ContextVerdict
from context.analyzer import ContextSnapshot
from scoring.confidence_v2 import ConfidenceResult, FactorScore
from datetime import datetime, timezone


async def main():
    sr_levels = {
        "4h": {
            "resistance": [3.85, 4.12, 4.45],
            "support": [3.25, 3.05, 2.80],
        },
        "1h": {
            "resistance": [3.62, 3.78],
            "support": [3.35, 3.18],
        },
    }

    factors = [
        FactorScore.make(name="HTF Trend", weight=15, raw=0.8),
        FactorScore.make(name="Structure", weight=25, raw=0.7),
        FactorScore.make(name="Liquidity", weight=15, raw=0.6),
        FactorScore.make(name="Volume", weight=10, raw=0.9),
        FactorScore.make(name="Funding", weight=5, raw=0.4),
        FactorScore.make(name="OI", weight=5, raw=0.5),
        FactorScore.make(name="RSI", weight=5, raw=0.7),
        FactorScore.make(name="MACD", weight=5, raw=0.6),
        FactorScore.make(name="ADX", weight=5, raw=0.5),
    ]
    confidence_v2 = ConfidenceResult(
        factors=factors,
        total_score=64.5,
        quality="moderate",
        recommendation="BUY",
    )

    result = SignalResult(
        signal=SignalType.BUY,
        symbol="NEAR/USDT",
        timeframe="1h",
        close=3.48,
        entry_price=3.48,
        sl=3.25,
        tp=4.12,
        score=5,
        reasons=[
            "Supertrend bullish (trend following)",
            "EMA aligned bullish (8 > 21 > 55)",
            "RSI выше 50 (60.2) — бычья зона",
            "MACD гистограмма растёт (+0.8%)",
            "Объём выше SMA на 35% (подтверждение)",
        ],
        sr_levels=sr_levels,
        level_warnings=["Цена вблизи сопротивления 3.62 (1h)"],
        _confirmed_tf="5m",
        _context_items=[
            "Fear & Greed: 52 (нейтральный) 😐",
        ],
        _context_score=0.3,
        _regime="uptrend",
        _regime_blocked=False,
        _confidence_v2=confidence_v2,
    )

    snapshot = ContextSnapshot(
        symbol="NEAR/USDT",
        timestamp=datetime.now(timezone.utc),
        fear_greed_value=52,
        fear_greed_label="Neutral",
        funding_rate=0.00012,
        open_interest_delta=3.5,
        long_short_ratio=1.25,
        news_sentiment_score=0.3,
        price_change_24h=4.2,
        is_trending=True,
    )

    context_verdict = ContextVerdict(
        verdict="WEAK",
        confidence=0.55,
        score=0.3,
        supporting=["Funding rate нейтральный", "OI растёт +3.5%"],
        opposing=["Fear & Greed нейтральный (52)", "Long/Short 1.25 — перекос в лонг"],
        snapshot=snapshot,
    )

    await send_signal(result, context_verdict=context_verdict)
    print("OK: Signal NEAR/USDT sent to channel!")


if __name__ == "__main__":
    asyncio.run(main())
