"""
strategy/levels.py — Расчёт уровней поддержки и сопротивления
"""
from typing import List, Dict, Tuple
import pandas as pd
from loguru import logger


def find_swing_levels(df: pd.DataFrame, window: int = 10) -> Tuple[List[float], List[float]]:
    """
    Находит локальные экстремумы (swing high / swing low) на OHLCV данных.

    Args:
        df: DataFrame со свечами (должен содержать columns 'high', 'low')
        window: количество свечей для поиска экстремума

    Returns:
        (resistances, supports) — отсортированные списки уровней
    """
    highs = []
    lows = []

    for i in range(window, len(df) - window):
        high_window = df['high'].iloc[i - window:i + window + 1]
        low_window = df['low'].iloc[i - window:i + window + 1]

        if df['high'].iloc[i] == high_window.max():
            highs.append(float(df['high'].iloc[i]))
        if df['low'].iloc[i] == low_window.min():
            lows.append(float(df['low'].iloc[i]))

    return sorted(set(highs), reverse=True)[:5], sorted(set(lows))[:5]


def cluster_levels(levels: List[float], threshold: float = 0.005) -> List[float]:
    """
    Объединяет уровни, которые ближе threshold% друг к другу.

    Args:
        levels: список уровней
        threshold: порог кластеризации (0.005 = 0.5%)

    Returns:
        отсортированный список кластеризованных уровней
    """
    if not levels:
        return []

    clustered = []
    levels = sorted(levels)
    cluster = [levels[0]]

    for level in levels[1:]:
        if (level - cluster[-1]) / cluster[-1] < threshold:
            cluster.append(level)
        else:
            clustered.append(round(sum(cluster) / len(cluster), 4))
            cluster = [level]
    clustered.append(round(sum(cluster) / len(cluster), 4))

    return clustered


def get_support_resistance(
    df: pd.DataFrame,
    current_price: float,
    window: int = 10,
    threshold: float = 0.005,
    max_levels: int = 2
) -> Dict[str, List[float]]:
    """
    Возвращает уровни поддержки и сопротивления.

    Args:
        df: DataFrame со свечами (OHLCV)
        current_price: текущая цена для фильтрации уровней
        window: размер окна для поиска swing
        threshold: порог кластеризации
        max_levels: максимальное количество уровней каждого типа

    Returns:
        {'resistance': [...], 'support': [...]}
    """
    raw_highs, raw_lows = find_swing_levels(df, window=window)

    resistances = cluster_levels(
        [h for h in raw_highs if h > current_price],
        threshold=threshold
    )
    supports = cluster_levels(
        [l for l in raw_lows if l < current_price],
        threshold=threshold
    )

    return {
        'resistance': resistances[:max_levels],
        'support': supports[:max_levels],
    }


def validate_levels_vs_trade(
    sr_levels: Dict[str, Dict[str, List[float]]],
    entry: float,
    sl: float,
    tp: float,
    is_buy: bool = True,
) -> List[str]:
    """
    Проверяет, не находится ли сильный уровень между входом и TP/SL.

    Args:
        sr_levels: уровни по таймфреймам {'1h': {...}, '4h': {...}}
        entry: цена входа
        sl: stop loss
        tp: take profit
        is_buy: True для лонга, False для шорта

    Returns:
        список предупреждений
    """
    warnings = []

    for timeframe, levels in sr_levels.items():
        if is_buy:
            # Для лонга: сопротивление между entry и TP — плохо
            for r in levels.get('resistance', []):
                if entry < r < tp:
                    warnings.append(
                        f"⚠️ Сопротивление {r} между входом и TP на {timeframe}"
                    )
            # Поддержка между SL и entry — хорошо, но если слишком близко к SL — риск
            for s in levels.get('support', []):
                if sl < s < entry:
                    dist_pct = (entry - s) / entry * 100
                    if dist_pct < 1.0:
                        warnings.append(
                            f"⚠️ Поддержка {s} слишком близко к входу на {timeframe} ({dist_pct:.1f}%)"
                        )
        else:
            # Для шорта: поддержка между entry и TP — плохо
            for s in levels.get('support', []):
                if tp < s < entry:
                    warnings.append(
                        f"⚠️ Поддержка {s} между входом и TP на {timeframe}"
                    )
            # Сопротивление между SL и entry — риск
            for r in levels.get('resistance', []):
                if entry < r < sl:
                    dist_pct = (r - entry) / entry * 100
                    if dist_pct < 1.0:
                        warnings.append(
                            f"⚠️ Сопротивление {r} слишком близко к входу на {timeframe} ({dist_pct:.1f}%)"
                        )

    return warnings


def format_levels_message(
    sr_levels: Dict[str, Dict[str, List[float]]],
) -> str:
    """
    Форматирует уровни S/R для вывода в Telegram сообщении.

    Args:
        sr_levels: уровни по таймфреймам

    Returns:
        HTML-строка для Telegram
    """
    lines = ["\n📐 <b>Уровни поддержки / сопротивления:</b>"]

    for tf in ['4h', '1h']:
        if tf not in sr_levels:
            continue

        levels = sr_levels[tf]
        tf_label = tf.upper()

        r_str = " / ".join(str(r) for r in levels.get('resistance', [])) or "—"
        s_str = " / ".join(str(s) for s in levels.get('support', [])) or "—"

        lines.append(f"┌─ {tf_label} {'─' * 30}")
        lines.append(f"│  🔴 Сопр.: {r_str}")
        lines.append(f"│  🟢 Подд.: {s_str}")
        lines.append(f"└{'─' * 34}")

    return "\n".join(lines)
