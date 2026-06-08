from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from tgbot.backtest.synthetic import make_trending_ohlcv
from tgbot.backtest.weight_sweep import run_profile_sweep
from tgbot.config.weights import DEFAULT_PROFILE, WeightProfile


def test_sweep_two_profiles_returns_dataframe():
    df = make_trending_ohlcv(n=300)
    profiles = [
        DEFAULT_PROFILE,
        dataclasses.replace(DEFAULT_PROFILE, name='strict', adx_min=30.0),
    ]
    result = run_profile_sweep(profiles, df)
    assert isinstance(result, pd.DataFrame)
    assert not result.empty
    assert 'profile_name' in result.columns
    assert 'metric' in result.columns
    assert 'value' in result.columns


def test_sweep_contains_expected_metrics():
    df = make_trending_ohlcv(n=300)
    result = run_profile_sweep([DEFAULT_PROFILE], df)
    metrics = set(result['metric'])
    for required in ('total_trades', 'winrate', 'profit_factor', 'max_drawdown'):
        assert required in metrics, f'Missing metric: {required}'


def test_sweep_two_profiles_different_adx():
    df = make_trending_ohlcv(n=300)
    lax = dataclasses.replace(DEFAULT_PROFILE, name='lax_adx', adx_min=10.0)
    strict = dataclasses.replace(DEFAULT_PROFILE, name='strict_adx', adx_min=50.0)
    result = run_profile_sweep([lax, strict], df)
    signals = result[result['metric'] == 'signals_generated'].set_index('profile_name')['value']
    # lax profile should generate at least as many signals as strict
    assert signals.get('lax_adx', 0) >= signals.get('strict_adx', 0)


def test_sweep_default_returns_same_as_separate_run():
    """Run same profile twice → identical results (determinism)."""
    from tgbot.backtest.engine import BacktestEngine

    df = make_trending_ohlcv(n=200)
    result_sweep = run_profile_sweep([DEFAULT_PROFILE], df)
    wr_sweep = result_sweep[result_sweep['metric'] == 'winrate']['value'].iloc[0]

    engine = BacktestEngine()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr('tgbot.config.settings.config.trading.adx_min', DEFAULT_PROFILE.adx_min)
        result_direct = engine.run(df)

    assert abs(wr_sweep - (result_direct.winrate or 0.0)) < 0.001
