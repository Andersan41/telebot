# Analytics Suite — Data-Driven Audit System

10 модулей для полного анализа торговой системы. Все читают из существующей `signals.db` — без изменений схемы.

## Quick Start

```bash
# После накопления 300+ закрытых сделок:

python -m analytics.trace_export --format csv       # 1. Полный экспорт
python -m analytics.trades_export --format json     # 2. Экспорт по сделкам
python -m analytics.gate_funnel                     # 3. Gate Funnel
python -m analytics.version_compare                 # 4. Сравнение версий
python -m analytics.drift_report --weeks 8          # 5. Drift Report
python -m analytics.counterfactual --export         # 6. Counterfactual
python -m analytics.distributions                   # 7. Distribution
python -m analytics.feature_drift                   # 8. Feature Drift
python -m analytics.calibration                     # 9. Calibration
python -m analytics.evolution --export-proposal     # 10. Evolution Engine
```

Все модули экспортируют в `reports/` через флаг `--export`.

---

## 1. DecisionTrace Export (`analytics/trace_export.py`)

Полный экспорт: `decision_traces × signal_candidates × signal_outcomes` в одну плоскую таблицу.

```bash
python -m analytics.trace_export                     # CSV по умолчанию
python -m analytics.trace_export --format json       # JSON
python -m analytics.trace_export --signal-only       # Только signal_generated=True
python -m analytics.trace_export --symbol BTC/USDT   # Фильтр по символу
python -m analytics.trace_export --since 2025-01-01  # Фильтр по дате
python -m analytics.trace_export --summary-only      # Только статистика
```

**Что даёт:**
- Экспорт 22 gate колонок + gate_path JSON + feature snapshot (25+ полей)
- Статистика по gate pass rates, final stage distribution, feature ranges
- Готово для pandas, sklearn, любого ML-пайплайна

**Поля экспорта:**
```
id, symbol, timeframe, timestamp, final_stage, blocked_reason,
signal_generated, signal_type, score, close_price, sl, tp,
strategy_version, config_snapshot, signal_id, candidate_id,
outcome, pnl_pct, gate_path,
gate_cooldown ... gate_dedup (22 колонки),
adx, rsi, ema_short, ema_long, ema_spread_pct, macd_hist,
supertrend_direction, volume_ratio, dmi_strength, ema_strength,
signal_score, confidence, regime, direction, sl_source,
tp_distance_pct, sl_distance_pct, rr_ratio, has_bos, has_sweep,
has_ob, ob_distance_pct, context_score, btc_trend_strength,
mtf_alignment_score, atr_pct, ema_slope_3, ema_slope_5,
nearest_support_pct, nearest_resistance_pct, regime_confidence
```

---

## 2. Per-Trade Export (`analytics/trades_export.py`)

По каждой закрытой сделке: symbol, direction, entry, sl, tp, exit, pnl, result, version, config_snapshot, decision_trace_id, candidate_id.

```bash
python -m analytics.trades_export                    # CSV
python -m analytics.trades_export --format json      # JSON
python -m analytics.trades_export --all              # Включая открытые
python -m analytics.trades_export --symbol ETH/USDT  # Фильтр
```

**Что даёт:**
- Attribution: какие факторы дают профит
- Feature importance: важность каждого признака
- Drift: изменение поведения факторов во времени
- Walk-forward: валидация на новых данных
- Version comparison: сравнение версий стратегии

**Поля экспорта:**
```
trade_id, symbol, direction, timeframe,
entry_price, sl, tp, exit_price, exit_status,
pnl_pct, result (WIN/LOSS/EXPIRED),
signal_created, outcome_closed,
strategy_version, config_snapshot,
decision_trace_id, candidate_id,
st_strength, ema_strength, macd_strength, rsi_strength,
vol_strength, adx_strength, dmi_strength, weighted_score,
adx, rsi, ema_fast, ema_slow, ema_trend,
macd_hist, dmi_plus, dmi_minus, atr, volume, volume_sma,
supertrend_direction, regime, regime_confidence,
blocked_gate, final_stage, gate_path,
score, confidence_v2_pct,
has_trigger, has_leading_trigger, mtf_aligned,
ema_spread_pct, volume_ratio, tp_distance_pct, sl_distance_pct,
rr_ratio, atr_pct, context_score, btc_trend_strength, mtf_alignment_score
```

---

## 3. Gate Funnel (`analytics/gate_funnel.py`)

Для каждого гейта: Entered / Passed / Dropped / TP / SL / WR / PF.

```bash
python -m analytics.gate_funnel                     # Полный отчёт
python -m analytics.gate_funnel --symbol BTC/USDT   # По символу
python -m analytics.gate_funnel --export            # Экспорт JSON
```

**Пример вывода:**
```
Gate                          Entered   Passed  Dropped   Drop%    TP    SL      WR      PF
────────────────────────── ──────── ──────── ──────── ─────── ───── ───── ─────── ───────
cooldown                      1,247    1,180       67    5.4%    45    32   58.4%    1.87
mtf_alignment                 1,180      890      290   24.6%    38    28   57.6%    1.72
rr_guard                        890      810       80    9.0%    35    25   58.3%    1.81
```

**Плюс Counterfactual таблица:**
```
Gate                          Blocked   Add  AddWR  CurWR  NewWR     ΔWR  Verdict
mtf_alignment                     42    42  52.4%  58.1%  57.8%   -0.3%  NEUTRAL
rr_guard                          18    18  61.1%  58.1%  58.4%   +0.3%  USEFUL
```

**Verdict:**
- `USEFUL` — гейт фильтрует плохие сделки (удалять нельзя)
- `NEUTRAL` — гейт бесполезен (можно убрать)
- `HARMFUL` — гейт вредит (нужно убрать)

---

## 4. Version Compare (`analytics/version_compare.py`)

Сравнение WR / PF / PnL между версиями + diff параметров из config_snapshot.

```bash
python -m analytics.version_compare                 # Все версии
python -m analytics.version_compare --versions 2.4.0 2.4.1  # Конкретные
python -m analytics.version_compare --export        # Экспорт
```

**Пример вывода:**
```
Version          Trades      WR      PF    AvgPnL   TotalPnL   BuyWR  SellWR
────────────── ──────── ─────── ─────── ──────── ────────── ─────── ───────
2.4.0               156   54.5%    1.72   +0.320%   +50.12%   56.2%   51.8%
2.4.1               203   58.1%    1.89   +0.410%   +83.23%   59.8%   55.3%
  ΔWR=+3.6%  ΔPF=+0.17

PARAMETER CHANGES BETWEEN VERSIONS:
2.4.0 → 2.4.1:
Parameter                         Old             New           Delta
────────────────────────────── ─────────────── ─────────────── ───────────────
adx_min                              22              26            +4
min_score_for_signal                  2               3            +1
mtf_required_alignment                2               1            -1
```

---

## 5. Drift Report (`analytics/drift_report.py`)

Еженедельный отчёт: WR по факторам и режимам. Детектирует когда фактор перестал работать.

```bash
python -m analytics.drift_report --weeks 8          # Последние 8 недель
python -m analytics.drift_report --export           # Экспорт
```

**Что показывает:**
- По каждому фактору: WR по неделям + значение фактора
- По каждому режиму: WR по неделям
- Автоматическое определение дрифта (DEGRADED / IMPROVED)

**Пример:**
```
ema_spread_pct ← DEGRADED (ΔWR=-4.2%)
Week      N      WR    AvgVal         P5        P95    AvgPnL
2025-W25   12   62.5%     0.4500     0.2100     0.8900   +0.520%
2025-W26    8   58.3%     0.5200     0.2800     0.9500   +0.380%
2025-W27   10   50.0%     0.7800     0.4500     1.2100   +0.120%
```

---

## 6. Counterfactual (`analytics/counterfactual.py`)

Что если убрать гейт? Сколько сделок добавится, как изменится WR/PF.

```bash
python -m analytics.counterfactual                  # Все гейты
python -m analytics.counterfactual --gate mtf_alignment  # Один гейт
python -m analytics.counterfactual --pairs          # Пары гейтов
python -m analytics.counterfactual --export         # Экспорт
```

**Пример вывода:**
```
Gate                          Blocked   Add  AddWR  NewWR     ΔWR   NewPF     ΔPF  Verdict
rr_guard                           18    18  61.1%  58.4%   +0.3%    1.91   +0.02  REMOVABLE
mtf_alignment                      42    42  52.4%  57.8%   -0.3%    1.82   -0.05  NEUTRAL
btc_global_trend                   28    28  39.3%  55.2%   -2.9%    1.45   -0.42  ESSENTIAL
```

**Pair removal (удаление двух гейтов):**
```
rr_guard + no_trade_zones          +12  trades  NewWR=59.2%  ΔWR=+1.1%
```

---

## 7. Distribution (`analytics/distributions.py`)

Распределения факторов: median, P5, P25, P75, P95, IQR — раздельно для TP и SL.

```bash
python -m analytics.distributions                   # Все факторы
python -m analytics.distributions --factor adx      # Один фактор
python -m analytics.distributions --export          # Экспорт
```

**Пример вывода:**
```
Factor                      N │  TP Median      TP P5     TP P95 │  SL Median      SL P5     SL P95 │    Sep
───────────────────────── ───── │ ────────── ────────── ────────── │ ────────── ────────── ────────── │ ──────
adx                          287 │     32.4000    21.0000    48.5000 │     24.1000    16.0000    35.2000 │  0.342 ★
rsi                          287 │     58.2000    42.1000    72.8000 │     51.3000    38.5000    65.4000 │  0.218
volume_ratio                 287 │      1.8500     0.9200     3.4100 │      1.4200     0.7800     2.5500 │  0.285 ★
```

**Sep = Separation score.** Чем выше — тем лучше фактор разделяет TP и SL.

**RECOMMENDED RANGES (из TP процентилей):**
```
Factor                  TP P25-P75 (IQR)                 TP P5-P95
────────────────────── ─────────────────────────── ───────────────────────────
adx                    [     26.5000,     38.2000]  [     21.0000,     48.5000]
rsi                    [     48.3000,     65.1000]  [     42.1000,     72.8000]
```

---

## 8. Feature Drift (`analytics/feature_drift.py`)

Сравнение ранних vs поздних сделок: сдвинулись ли оптимальные диапазоны признаков.

```bash
python -m analytics.feature_drift                   # Авто-split 50/50
python -m analytics.feature_drift --split-ratio 0.3 # 30/70 split
python -m analytics.feature_drift --threshold 15    # Порог дрифта
python -m analytics.feature_drift --export          # Экспорт
```

**Что показывает:**
- Median shift: сместилась ли медиана
- IQR change: изменился ли разброс
- P5-P95 shift: сдвинулись ли границы
- Severity: HIGH / MEDIUM / LOW

**Пример:**
```
Feature                  Early Med   Late Med      Shift  NormShift   Early IQR    Late IQR   IQR Δ%  Severity
ema_spread_pct              0.4500      0.8200   +0.3700      0.412      0.3200      0.4800  +50.0%  HIGH
volume_ratio                1.8500      2.1200   +0.2700      0.285      1.2000      1.4500  +20.8%  MEDIUM
```

---

## 9. Calibration (`analytics/calibration.py`)

Совпадает ли уверенность модели с реальным WR?

```bash
python -m analytics.calibration                     # По confidence_v2_pct
python -m analytics.calibration --export            # Экспорт
```

**Пример вывода:**
```
Predicted        N  Wins  Losses   Actual WR   Avg Conf  Cal Error    Avg PnL
──────────── ───── ───── ─────── ────────── ────────── ────────── ─────────
40-50%           34    16      18      47.1%     44.2%      2.9%   -0.080%
50-60%           52    28      24      53.8%     55.1%      1.3%   +0.210%
60-70%           41    26      15      63.4%     64.8%      1.4%   +0.450%
70-80%           28    19       9      67.9%     73.2%      5.3%   +0.620%
80-90%           12     9       3      75.0%     84.1%      9.1%   +0.890%

Calibration verdict: MODERATELY CALIBRATED
Brier Score:    0.1842 (0=perfect, 1=worst)
ECE:            4.20%
```

**By regime:**
```
trend              N= 156  WR=61.5%  AvgConf=62.3%  ECE=3.8%
range              N=  89  WR=48.3%  AvgConf=52.1%  ECE=5.2%
```

---

## 10. Evolution Engine (`analytics/evolution.py`)

Автоматическая оптимизация весов через walk-forward. Тренирует GradientBoosting + isotonic calibration, предлагает новые веса.

```bash
python -m analytics.evolution                       # Минимум 100 сделок
python -m analytics.evolution --splits 5            # 5 fold walk-forward
python -m analytics.evolution --export-proposal     # Экспорт предложения
python -m analytics.evolution --apply               # Применить веса в bot_settings
```

**Пример вывода:**
```
WALK-FORWARD FOLD RESULTS
 Fold  Train    Test    Acc    AUC   Brier  TestWR  PredWR
    1    320     80   58.8%  0.612  0.2104   55.0%   57.2%
    2    400     80   61.3%  0.634  0.1987   57.5%   59.1%
    3    480     80   57.5%  0.598  0.2201   52.5%   55.8%
    4    560     80   62.5%  0.645  0.1856   60.0%   61.3%

FEATURE IMPORTANCE (from GradientBoosting)
 Rank  Feature                Importance
──────── ──────────────────── ──────────
    1  adx_strength              0.1842 *
    2  dmi_strength              0.1523 *
    3  volume_ratio              0.1201
    4  rsi_strength              0.1089 *
    5  ema_spread_pct            0.0967

OPTIMAL WEIGHTS vs CURRENT WEIGHTS
Factor             Current    Optimal      Delta  Action
st_strength          0.1500     0.1200   -0.0300  ↓ 0.030
adx_strength         0.1000     0.1800   +0.0800  ↑ 0.080
dmi_strength         0.1000     0.1500   +0.0500  ↑ 0.050
rsi_strength         0.1500     0.1100   -0.0400  ↓ 0.040
```

---

## Архитектура

```
analytics/
├── __init__.py              # Package init
├── trace_export.py          # 1. Full DecisionTrace export
├── trades_export.py         # 2. Per-trade export
├── gate_funnel.py           # 3. Gate funnel analysis
├── version_compare.py       # 4. Strategy version comparison
├── drift_report.py          # 5. Weekly drift report
├── counterfactual.py        # 6. Counterfactual gate analysis
├── distributions.py         # 7. Factor distributions
├── feature_drift.py         # 8. Feature drift detection
├── calibration.py           # 9. Probability calibration
├── evolution.py             # 10. Evolution engine
├── factor_stats.py          # Per-factor WR/PF/expectancy (legacy)
└── entry_delay.py           # Entry timing analysis (legacy)
```

## Зависимости

Все модули используют только уже установленные пакеты:
- `sqlite3`, `json`, `csv`, `argparse` — stdlib
- `numpy` — уже в requirements.txt
- `scikit-learn` — уже в requirements.txt (для evolution.py и calibration.py)
- `loguru` — уже в requirements.txt

## Интеграция с существующей инфраструктурой

- Читают из `data/signals.db` (таблицы: `decision_traces`, `signal_candidates`, `signals`, `signal_outcomes`)
- Используют те же gate колонки что и `DecisionTraceBuilder` (`storage/trace.py`)
- Используют те же gate ordering что и `scanner.py` / `get_trace_stats()` / `get_counterfactual()`
- `config_snapshot` в `decision_traces` хранит параметры стратегии — version_compare читает их для diff
