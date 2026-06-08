#!/usr/bin/env python3
"""Скрипт для прогона sweep-тестов по WeightProfile-вариантам."""

from __future__ import annotations

import argparse
import sys

import matplotlib.pyplot as plt

from tgbot.backtest.synthetic import make_trending_ohlcv
from tgbot.backtest.weight_sweep import run_profile_sweep
from tgbot.config.weights import DEFAULT_PROFILE, WeightProfile


def build_sweep_profiles() -> list[WeightProfile]:
    """Создать набор профилей для сравнения."""
    base = DEFAULT_PROFILE
    adx_variants: list[WeightProfile] = [
        base.replace(name='adx_20', adx_min=20.0),
        base.replace(name='adx_24', adx_min=24.0),
        base.replace(name='adx_28', adx_min=28.0),
    ]
    rsi_variants: list[WeightProfile] = [
        base.replace(name='rsi_ob_75', rsi_overbought=75.0, rsi_oversold=25.0),
        base.replace(name='rsi_ob_70', rsi_overbought=70.0, rsi_oversold=30.0),
    ]
    return adx_variants + rsi_variants


def main() -> None:
    parser = argparse.ArgumentParser(description='Sweep WeightProfile variants')
    parser.add_argument('--candles', type=int, default=500, help='Number of synthetic candles')
    parser.add_argument('--plot', action='store_true', help='Show a summary plot')
    args = parser.parse_args()

    print('Генерация синтетических данных...', file=sys.stderr)
    df = make_trending_ohlcv(n=args.candles)

    profiles = build_sweep_profiles()
    print(f'Запуск sweep для {len(profiles)} профилей...', file=sys.stderr)

    results = run_profile_sweep(profiles, df)

    if results.empty:
        print('Нет результатов!', file=sys.stderr)
        sys.exit(1)

    pivot = results.pivot_table(index='profile_name', columns='metric', values='value')
    print('\n=== Сводка ===')
    print(pivot.to_string(float_format='%.2f'))

    if args.plot and 'winrate' in results['metric'].values:
        wr = results[results['metric'] == 'winrate']
        if not wr.empty:
            wr.plot(kind='bar', x='profile_name', y='value', legend=False)
            plt.title('Winrate by profile')
            plt.ylabel('Winrate (%)')
            plt.tight_layout()
            plt.show()


if __name__ == '__main__':
    main()
