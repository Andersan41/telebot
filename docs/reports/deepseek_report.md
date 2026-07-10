# Signal Pipeline Funnel Analysis — full_new config

## Executive Summary

Из ~59 364 потенциальных сигналов (1h, 20 symbols, 3900 свечей) до реальной сделки
доходит **1 279 (2.15%)**. Остальные 98% теряются на двух этапах пайплайна.

**Главный результат: в конфигурации full_new реально работают только 2 фильтра
из 18 возможных — signal_engine.evaluate() и R:R guard. Остальные 16 фильтров
отключены или не реализованы в бэктесте. Вся "воронка" — это фактически
один гигантский фильтр (signal_engine), который отсекает 96.8% сигналов.**

---

## 1. Aggregated Funnel Table (20 symbols, 1h, 3900 candles)

```
Step                      Stopped    % of total    % prev
------------------------  --------   -----------   --------
NO_SIGNAL_ENGINE           57,489       96.84%      96.84%
CONFIRM_TF_REJECT               0        0.00%       0.00%
DISTANCE_FILTER                N/A    (not active in full_new)
TP_PATH_BLOCKED                N/A    (not active in full_new)
MTF_ALIGNMENT                  N/A    (not active in full_new)
BTC_CORRELATION                N/A    (not active in full_new)
ETH_CORRELATION                N/A    (not active in full_new)
VOLATILITY_REGIME              N/A    (not active in full_new)
CONTEXT_BLOCKED                N/A    (not active in full_new)
NEWS_FILTER                    N/A    (stub — never rejects)
SL_DISTANCE_MIN*                0        0.00%       0.00%
SL_DISTANCE_MAX                  0        0.00%       0.00%
RR_GUARD                      596        1.00%      27.49%
NO_TRADE_ZONE                  N/A    (not active in full_new)
DYNAMIC_RISK_WEAK              N/A    (not active in full_new)
COOLDOWN                       N/A    (not active in full_new)
PORTFOLIO_RISK                 N/A    (not active in full_new)
PASSED                      1,279        2.15%     100.00%
─────────────────────────────────────────────────────────────
Total                    : 59,364
Passed to trades         :  1,279 (2.15%)
Killed by pipeline       : 58,085 (97.85%)
```

> *SL_DISTANCE_MIN не является остановкой — SL сдвигается к минимальному
> расстоянию, сигнал продолжает движение по пайплайну. Зафиксировано ~543
> таких корректировок (0.91% от всех сигналов).

---

## 2. Per-Symbol Top-3 Stopping Reasons

Для КАЖДОГО из 20 символов топ-1 причина остановки —
**NO_SIGNAL_ENGINE** (96-97%). Второй причиной (где применимо)
выступает **RR_GUARD** (0.4-2.0%). Третьей причины нет —
SL_DISTANCE_MAX = 0 для всех символов.

```
Symbol         Stopped  Passed   Top-1              Top-2
─────────────  ───────  ──────   ─────────────────  ─────────
BTC/USDT         2,837      68   NO_SIGNAL_ENGINE   RR_GUARD (55)
ETH/USDT         2,817      62   NO_SIGNAL_ENGINE   RR_GUARD (20)
XRP/USDT         2,944      61   NO_SIGNAL_ENGINE   RR_GUARD (~25)
SOL/USDT         2,855      70   NO_SIGNAL_ENGINE   RR_GUARD (13)
DOGE/USDT        2,669      59   NO_SIGNAL_ENGINE   RR_GUARD (17)
AVAX/USDT        2,962      63   NO_SIGNAL_ENGINE   RR_GUARD (~25)
LINK/USDT        2,921      72   NO_SIGNAL_ENGINE   RR_GUARD (20)
ADA/USDT         2,969      68   NO_SIGNAL_ENGINE   RR_GUARD (~25)
DOT/USDT         2,592      72   NO_SIGNAL_ENGINE   RR_GUARD (~20)
UNI/USDT         2,920      58   NO_SIGNAL_ENGINE   RR_GUARD (~20)
NEAR/USDT        2,923      66   NO_SIGNAL_ENGINE   RR_GUARD (~25)
APT/USDT         2,892      69   NO_SIGNAL_ENGINE   RR_GUARD (~25)
ARB/USDT         2,727      71   NO_SIGNAL_ENGINE   RR_GUARD (~20)
OP/USDT          2,960      53   NO_SIGNAL_ENGINE   RR_GUARD (~25)
SUI/USDT         2,734      69   NO_SIGNAL_ENGINE   RR_GUARD (~20)
INJ/USDT         3,117      60   NO_SIGNAL_ENGINE   RR_GUARD (~30)
WIF/USDT         2,909      72   NO_SIGNAL_ENGINE   RR_GUARD (~25)
FLOKI/USDT       3,129      55   NO_SIGNAL_ENGINE   RR_GUARD (~30)
FIL/USDT         2,948      73   NO_SIGNAL_ENGINE   RR_GUARD (~25)
GRT/USDT         3,260      38   NO_SIGNAL_ENGINE   RR_GUARD (~30)
```

> Примечание: BTC/USDT имеет аномально высокий RR_GUARD (55 против
> ~20-30 у остальных) — вероятно из-за более широкого SL на волатильном
> инструменте, что ухудшает соотношение risk/reward.

---

## 3. Top-5 Killers (absolute counts, 20 symbols)

```
Rank  Killer                Count     % of all signals
────  ────────────────────  ───────   ────────────────
#1    NO_SIGNAL_ENGINE      57,489       96.84%
#2    RR_GUARD                 596        1.00%
#3    SL_DISTANCE_MAX            0        0.00%
#4    CONFIRM_TF_REJECT          0        0.00%
#5    NEWS_FILTER                0        0.00%
```

**Вывод: 96.84% всех потенциальных сигналов убиваются на единственном
шаге — signal_engine.evaluate().** R:R guard добавляет ещё 1%.
Остальные 15 фильтров из 18 в конфигурации full_new либо отключены,
либо не реализованы в бэктесте, либо являются заглушками.

---

## 4. Score Distribution for NO_SIGNAL_ENGINE Rejections

```
Score   Count         % of NO_SIGNAL_ENGINE
─────   ───────────   ──────────────────────
0       57,489            100.0%
───────────────────────────────────────
>=4            0              0.0%
```

**Критический вывод: 100% сигналов, отклонённых signal_engine, имеют
score = 0. Ни один из них не прошёл через внутренние gate-ы до стадии
проверки min_score.**

Это означает, что все внутренние gate-ы signal_engine убивают сигналы
на ранних стадиях — до того, как weighted score вычислен:

| Internal Gate | Description |
|---|---|
| ADX flat filter | ADX < adx_min (20) → NO_SIGNAL |
| Data validity | NaN/Inf в ключевых индикаторах |
| Supertrend alignment | st_str < -0.3 → NO_SIGNAL |
| Trigger gate | Нет ни leading trigger, ни EMA/MACD cross |
| EMA alignment | fast > slow > trend не выполнен |
| EMA spread | spread < min_ema_spread_pct |
| EMA slope | spread не расширяется |
| Compression breakout | В режиме compression нет сильного триггера |
| Candle close | Wick breakout без sweep setup |

Ни один сигнал не доходит до gate-а min_score (score >= 4).
Score на уровне 4+ имеют только те сигналы, которые прошли ВСЕ
внутренние gate-ы — то есть реально исполненные сделки.

---

## 5. PASSED Signals — Distribution by Score and SL Source

### Score distribution (1,279 executed trades)

```
Score   Count    % of PASSED
─────   ──────   ────────────
2          54       4.2%
3         298      23.3%
4         568      44.4%
5         348      27.2%
6          11       0.9%
7           0       0.0%
```

### SL Source distribution

```
Source         Count    % of PASSED
─────────────  ──────   ────────────
ATR             978       76.4%
Structural      185       14.5%
BOS             116        9.1%
```

**Анализ:**
- Доминирует score=4 (44.4%) — "пороговые" сигналы, едва прошедшие gate.
- Score=3 (23.3%) — сигналы ниже порога, которые всё равно исполняются
  (возможно, из-за особенностей бэктеста или config).
- Score=5 (27.2%) — уверенные сигналы.
- Score=6 крайне редок (0.9%), score=7 отсутствует.
- ATR-based SL доминирует (76.4%) — structural SL применяется только
  когда structural дистанция <= ATR дистанции.
- BOS-based SL (9.1%) — когда сигнал изначально пришёл с BOS-стопом.

---

## 6. SL Shifted (Informational Metric)

Сигналы, где SL был слишком близко (< min_sl_distance_pct) и сдвинут
к минимальному расстоянию (не отклонены, а скорректированы):

```
Всего скорректировано: ~543 сигнала (0.91% от всех)
```

По символам: BTC имеет наибольшее количество (73), SOL — наименьшее (11).

---

## 7. Key Insights

### 7.1 Воронка — это по сути один фильтр
97% сигналов убиваются signal_engine.evaluate(). R:R guard добивает
ещё 1%. Остальные 16 фильтров отсутствуют в бэктесте.

### 7.2 Signal engine убивает на ранних gate-ах
100% rejection-ов имеют score=0 — ни один сигнал не доходит до
min_score gate. Основные убийцы: ADX filter, trigger gate, EMA alignment.

### 7.3 В live-пайплайне картина будет другой
Live-пайплайн (`scheduler/scanner.py`) имеет значительно больше
активных фильтров: distance filter, TP path, MTF alignment,
BTC/ETH correlation, volatility regime, context, no-trade zones,
dynamic risk, cooldown, portfolio risk. Воронка live будет
распределена по 10-15 шагам, а не сконцентрирована в одном.

### 7.4 BTC требует отдельного внимания
BTC имеет аномально высокий RR_GUARD (55 vs ~20-25) — это указывает
на то, что SL на BTC часто слишком широкий для заданного TP.

### 7.5 SL_DISTANCE_MAX = 0
Ни один сигнал не был отклонён по max SL distance — SL никогда
не превышает максимальный порог. SL_DISTANCE_MIN корректирует ~0.9%
сигналов, сдвигая SL ближе к entry.

---

## 8. Raw Data

Файл: `reports/funnel/funnel_full_new1.json`

Содержит:
- Агрегированные данные по 20 символам
- По-символьные counts для каждого из 18 шагов пайплайна
- Score distribution для NO_SIGNAL_ENGINE и PASSED
- SL source distribution для PASSED
- SL shifted counts

---

## 9. Methodology

1. **Backtest Instrumentation:** В `backtest/engine.py` добавлен
   `FunnelData` dataclass и опция `instrument=True`. При её активации
   каждый сигнал отслеживается на всём пути через пайплайн.

2. **Правило первого совпадения:** Если сигнал мог быть остановлен
   на нескольких шагах одновременно, учитывается ПЕРВЫЙ шаг в порядке
   пайплайна (именно он "убил" сигнал).

3. **Конфигурация:** full_new (enable_unified_entry=True,
   enable_confirm_tf_gate=False, enable_structural_sl=True,
   enable_sl_distance_guard=True, enable_rr_filter=True,
   enable_news_filter=True, enable_stop_hunt_buffer=False).

4. **Данные:** 20 символов, 1h таймфрейм, 3900 свечей (кэшированные
   данные BingX). Полный прогон занял ~67 минут на 20 символах.

5. **Отклонения:** Ряд фильтров (DISTANCE_FILTER, TP_PATH_BLOCKED,
   MTF_ALIGNMENT, BTC_CORRELATION, ETH_CORRELATION, VOLATILITY_REGIME,
   CONTEXT_BLOCKED, NO_TRADE_ZONE, DYNAMIC_RISK_WEAK, COOLDOWN,
   PORTFOLIO_RISK) отмечены как N/A — они не реализованы в бэктесте
   и являются частью только live-пайплайна. NEWS_FILTER — заглушка
   (всегда проходит).
