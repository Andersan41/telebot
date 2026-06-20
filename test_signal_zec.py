"""
Тестовое уведомление сигнала для ZEC/USDT в Telegram канал.
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
            "resistance": [58.50, 62.00, 66.80],
            "support": [48.20, 45.00, 41.50],
        },
        "1h": {
            "resistance": [54.30, 56.80],
            "support": [50.10, 47.60],
        },
    }

    factors = [
        FactorScore.make(name="Supertrend", weight=5, raw=1.0),
        FactorScore.make(name="EMA", weight=10, raw=0.8),
        FactorScore.make(name="MACD", weight=10, raw=0.7),
        FactorScore.make(name="RSI", weight=5, raw=0.6),
        FactorScore.make(name="Volume", weight=15, raw=0.9),
        FactorScore.make(name="ADX", weight=5, raw=0.5),
        FactorScore.make(name="DMI", weight=5, raw=0.4),
    ]
    confidence_v2 = ConfidenceResult(
        factors=factors,
        total_score=52.3,
        quality="moderate",
        recommendation="BUY",
    )

    result = SignalResult(
        signal=SignalType.BUY,
        symbol="ZEC/USDT",
        timeframe="4h",
        close=52.15,
        entry_price=52.15,
        sl=48.20,
        tp=62.00,
        score=5,
        reasons=[
            "Supertrend aligned",
            "EMA8 пересекла EMA21 снизу вверх",
            "MACD бычий (norm=0.08%)",
            "RSI=58.3 — бычья зона",
            "ADX=28.4 (strong trend ≥ 22)",
            "Delta: +22% (покупки доминируют)",
        ],
        sr_levels=sr_levels,
        level_warnings=[],
        _confirmed_tf="15m",
        _context_items=[
            "Fear & Greed: 48 (Neutral) 😐",
        ],
        _context_score=0.2,
        _regime="uptrend",
        _regime_blocked=False,
        _confidence_v2=confidence_v2,
        _factor_strengths={
            "Supertrend": 1.0,
            "EMA": 0.8,
            "MACD": 0.7,
            "RSI": 0.6,
            "Volume": 0.9,
            "ADX": 0.5,
            "DMI": 0.4,
            "BUY": 0.42,
            "SELL": -0.42,
        },
        _weighted_score=21.0,
        _has_trigger=True,
        _has_leading_trigger=True,
    )

    snapshot = ContextSnapshot(
        symbol="ZEC/USDT",
        timestamp=datetime.now(timezone.utc),
        fear_greed_value=48,
        fear_greed_label="Neutral",
        funding_rate=0.00008,
        open_interest_delta=4.2,
        long_short_ratio=1.15,
        news_sentiment_score=0.1,
        price_change_24h=3.8,
        is_trending=False,
    )

    context_verdict = ContextVerdict(
        verdict="CONFIRMED",
        confidence=0.72,
        score=0.5,
        supporting=["Funding rate нейтральный", "OI растёт +4.2%", "Price momentum +3.8%"],
        opposing=["Fear & Greed нейтральный (48)"],
        snapshot=snapshot,
    )

    await send_signal(result, context_verdict=context_verdict)
    print("OK: Signal ZEC/USDT sent to channel!")


if __name__ == "__main__":
    asyncio.run(main())
