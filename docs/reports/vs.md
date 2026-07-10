# A/B: min_score_for_signal 2 → 5

**Date**: 2026-06-24
**Presets**: `full_new` (min_score=2) vs `score5_only` (min_score=5)
**Symbols**: 20 | **Candles**: 3,900 per symbol | **TF**: 1h | **Confirm TF**: 15m

---

## 1. Сравнительная таблица

| Метрика | full_new | score5_only | Δ |
|---|---|---|---|
| Trades | 1138 | 477 | -661 (−58%) |
| Win Rate % | 48.8% | 54.7% | +5.9pp |
| Avg Net PnL % | +0.996% | +1.341% | +0.345% |
| Total Net PnL % | +1133.4% | +639.6% | −493.9% |
| Profit Factor | 2.29 | 2.75 | +0.46 |
| Max Drawdown % | 18.69% | 23.81% | +5.12pp |
| Avg R:R | 1.63 | 1.66 | +0.03 |
| Signals Rejected (RR) | 232 | 168 | -64 |
| Signals Rejected (SL dist) | 43 | 42 | -1 |
| SL source: ATR | 810 | 351 | -459 |
| SL source: BOS | 145 | 83 | -62 |
| SL source: Structural | 183 | 43 | -140 |

---

## 2. Per-Symbol Breakdown

| Symbol | fn Trades | fn PnL(net) | s5 Trades | s5 PnL(net) | ΔTrades |
|---|---|---|---|---|---|
| BTC/USDT | 74 | +17.32% | 28 | +11.94% | -46 |
| ETH/USDT | 58 | +57.63% | 37 | +38.51% | -21 |
| XRP/USDT | 57 | +48.18% | 32 | +37.57% | -25 |
| SOL/USDT | 63 | +72.79% | 29 | +59.39% | -34 |
| DOGE/USDT | 54 | +63.29% | 21 | +50.43% | -33 |
| AVAX/USDT | 57 | +39.78% | 23 | +25.43% | -34 |
| LINK/USDT | 73 | +54.06% | 31 | +60.74% | -42 |
| ADA/USDT | 56 | +46.81% | 29 | +42.95% | -27 |
| DOT/USDT | 51 | +29.69% | 20 | +30.86% | -31 |
| UNI/USDT | 53 | +85.08% | 21 | +54.26% | -32 |
| NEAR/USDT | 70 | +84.76% | 26 | +27.97% | -44 |
| APT/USDT | 51 | +46.52% | 18 | +26.45% | -33 |
| ARB/USDT | 64 | +129.31% | 24 | +48.25% | -40 |
| OP/USDT | 40 | +39.27% | 17 | +25.36% | -23 |
| SUI/USDT | 73 | +97.68% | 32 | +58.70% | -41 |
| INJ/USDT | 53 | +45.37% | 15 | **-10.51%** | -38 |
| WIF/USDT | 54 | +53.09% | 29 | +26.05% | -25 |
| FLOKI/USDT | 49 | +34.93% | 15 | +5.17% | -34 |
| FIL/USDT | 61 | +48.99% | 23 | +4.06% | -38 |
| GRT/USDT | 27 | +38.91% | 7 ⚠ | +15.99% | -20 |

---

## 3. Score Distribution (score5_only)

| Score | Trades | % |
|---|---|---|
| 5 | 457 | 95.8% |
| 6 | 19 | 4.0% |
| 7 | 1 | 0.2% |
| **Total** | **477** | **100.0%** |

---

## 4. Анализ

### Качество vs Количество

score5_only отсекает **58% сделок** (1138 → 477), но显著но улучшает качество:

- **Winrate +5.9pp** (48.8% → 54.7%)
- **Avg Net PnL +34.5%** (+0.996% → +1.341%)
- **Profit Factor +20%** (2.29 → 2.75)

### Откуда берётся edge

Из score.md известно: score=5 имеет WR 60.6% и avg PnL +1.95% — единственный порог с выраженным edge. score=2-4 (WR 41-46%) — coin-flip, который размывает статистику.

### Max Drawdown растёт

+5.12pp (18.69% → 23.81%). Причина: меньше сделок = меньше диверсификация = выше концентрация. На коротких сериях это критично. На 3900 свечей (162 дня) — приемлемо.

### Единственный убыточный символ

**INJ/USDT**: PF=0.72, WR=26.7%, −10.51%. Единственный символ в минусе. При 15 сделках статистика ненадёжна — может быть шум.

### GRT/USDT

7 сделок — на таком объёме результат ненадёжен (⚠).

### Per-Symbol: LINK и SOL выигрывают

| Символ | ΔPnL(net) |
|---|---|
| LINK/USDT | +6.68% |
| SOL/USDT | -13.40% |
| DOGE/USDT | -12.86% |

LINK — единственный, где score5_only даёт **больше** PnL(net) в абсолютных величинах (+60.74% vs +54.06%). Остальные теряют из-за меньшего количества сделок, но выигрывают по quality.

---

## 5. Рекомендация

min_score=5 **улучшает качество сигнала** (WR, PF, avg PnL), но **снижает Total PnL** за счёт меньшего количества сделок. Trade-off:

| Сценарий | Рекомендация |
|---|---|
| Максимум Total PnL | full_new (min_score=2) — больше сделок, больше абсолютная отдача |
| Максимум quality/risk | score5_only (min_score=5) — лучше WR, PF, weniger noise |
| Баланс | min_score=4 или min_score=3 как компромисс |

**Ключевой инсайт из score.md**: score=5 — единственный порог с WR > 60% и avg PnL > 1.5%. Все пороги ниже — статистический шум.

---

## 6. Реализация

### Изменения в коде

| Файл | Изменение |
|---|---|
| `backtest/engine.py:218` | Добавлено `min_score_for_signal: Optional[int] = None` в `BacktestConfig` |
| `backtest/run_r6_batch.py:109-114` | Пресет `score5_only` (флаги identical `full_new`, `min_score_for_signal=5`) |
| `backtest/run_r6_batch.py:321-330` | `run_symbol_batch()` принимает `presets`/`preset_order` параметры |
| `backtest/run_r6_batch.py:411-413` | Save/restore override `config.scoring.min_score_for_signal` per-preset |

### Как работает override

```
BacktestConfig.min_score_for_signal = 5
    ↓
config.scoring.min_score_for_signal = 5  (temp override)
    ↓
signal_engine.evaluate() — читает из config.scoring
    ↓
config.scoring.min_score_for_signal = restore
```

signal_engine.py **не изменён**. min_score=5 применяется **только** внутри backtest-цикла.

### Кэш snapshots

Precomputed snapshots (indicators + structure + sweeps + OBs) закэшированы в `reports/abn/snapshot_cache/` (20 файлов, ~123MB). Повторные прогоны — ~6s на 20 символов.
