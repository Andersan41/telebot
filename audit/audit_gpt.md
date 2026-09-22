# Независимый аудит торгового бота ICT — logic_up

**Дата аудита:** 2026-09-08  
**Аудируемая версия:** 2.5.0  
**Назначение документа:** передача модели MIMO v2.5 в OpenCode для безопасного анализа и последующей модификации кода.

---

## 0. Итоговый вердикт

Бот построен как многоступенчатый ICT pipeline: Pattern Engine → Feature Builder → Probability Engine → Risk Engine, с дополнительными HTF, liquidity, market-phase, scenario и execution слоями.

Архитектура в целом зрелая: есть отдельные модули для структуры, ликвидности, trade plan, probability, risk, execution и audit-trace; последний закрытый audit сообщает о 35 audit-call точках и 46/47 reason codes. Важным преимуществом является отказ от анализа незакрытой свечи: `fetch_ohlcv` отбрасывает последний открытый бар. Также уже устранён feedback loop, в котором RR искусственно повышал P(TP). [Источник: `bot_audit(1).md`, разделы 1, 4, 23–29]

### Независимая оценка

**Сильные стороны**
- Хорошая модульная декомпозиция.
- ICT-структура основана на sweep / MSS / BOS / OB / FVG, а не на наборе обычных индикаторных сигналов.
- Есть отдельный liquidity-first Trade Engine.
- Есть hard risk/execution protection.
- Есть audit trace с snapshot признаков и config version.
- Есть outcome tracker и аналитические overlays.
- Есть различение setup detection и entry trigger.

**Основные зоны риска**
1. Confirmation score `>=2` фактически не фильтрует continuation setup с BOS-only.
2. OB retest остаётся hard gate и требует одновременно валидный OB, touch и confirmation candle.
3. HTF Bias остаётся directional veto для reversal, что противоречит идее reversal от HTF POI.
4. Premium/Discount выключен; при этом документ указывает A/B ухудшение PF при его использовании — эту функцию нельзя включать на основании intuition.
5. Kelly не реализует полноценное увеличение риска: текущий `min(kelly * 100, base_risk_pct)` позволяет Kelly только уменьшать fixed risk.
6. `ob_aware` cooldown может полностью обходить ранний cooldown и зависит от наличия OB.
7. Есть несогласованность между конфигурационным `min_rr_threshold=1.5` и фактическим hard gate Risk Engine `min_rr_ratio=2.0`.
8. Есть несогласованность документации/семантики вокруг количества reason codes: таблица говорит 46, changelog перечисляет 47.
9. Ещё не доказана причинная ценность большинства soft features; их нужно оценивать out-of-sample, а не считать edge автоматически.

### Главный принцип

**Сейчас не следует делать широкую оптимизацию.** Сначала зафиксировать baseline текущей версии, собрать однородные live outcomes и использовать audit log для counterfactual исследований. Любое изменение параметра ниже должно считаться гипотезой, если оно не относится к однозначному bug/data-integrity/contract issue.

---

# 1. Архитектура и pipeline

Текущий `scan_symbol_v2()` содержит примерно 30 gate checks и проходит через Phase 0–8: capital protection → pattern → setup gates → trade plan → overlays → feature build → probability → risk → trigger → dedup → execution/save/notify. [Источник: раздел 4]

## Оценка

Архитектурное разделение хорошее. Главная проблема не в количестве компонентов как таковом, а в том, что несколько разных функций частично дублируют друг друга:

- Pattern validity;
- Confirmation score;
- OB retest;
- HTF bias;
- Probability score;
- Risk gate;
- Entry trigger.

MIMO **не должна объединять эти компоненты без доказательства**, поскольку их назначение различается.

### Правильная семантика слоёв

```text
STRUCTURAL VALIDITY
    = есть ли вообще ICT setup?

SETUP QUALITY
    = насколько setup статистически качественный?

TRADE ECONOMICS
    = достаточно ли payoff относительно вероятности и costs?

ENTRY TRIGGER
    = есть ли сейчас корректный момент исполнения?

RISK / EXECUTION
    = допустима ли сделка с точки зрения капитала и market execution?
```

Нельзя превращать все эти вопросы в один score.

---

# 2. Сканирование и таймфреймы

Основные TF: `1h,4h`; цикл запускается каждые 15 минут и сканирует symbol × timeframe. Multi-TF режим опционален, confirm TF по умолчанию — 5m. [Источник: разделы 2–3]

## Наблюдение: частота 15m для 1h/4h

Само по себе это не баг. Однако для закрытой 1h/4h свечи четыре/шестнадцать запусков могут повторно оценивать один и тот же закрытый market state.

Это делает **event dedup и versioning состояния** особенно важными.

### Рекомендация

Не менять частоту пока. Добавить в analysis dataset:

```text
bar_close_timestamp
scan_timestamp
setup_event_id
```

и измерять, сколько уникальных setup events возникает на одну закрытую свечу.

---

# 3. Cooldown / Dedup — подозрительная область

Текущие значения:

- 1h: effective cooldown 120 min;
- 4h: effective cooldown 480 min;
- `cooldown_mode=ob_aware` по умолчанию;
- different OB может обходить cooldown;
- same OB получает сокращённый cooldown. [Источник: разделы 2, 14, 22]

## Проблема

В `ob_aware` early cooldown gate фактически пропускается, а реальная проверка переносится в Phase 6. Если нового OB нет, cooldown может фактически не работать. Это прямо отмечено в текущем аудите. [Источник: раздел 28]

### Риск

Два разных OB могут быть частью **одного и того же underlying market event**:

```text
liquidity event
→ displacement
→ MSS/BOS
→ несколько производных OB/FVG
```

Тогда bypass по другому OB может разрешить повторные сигналы, хотя рынок не сформировал новый независимый setup.

### Рекомендация

Добавить `setup_event_id`, минимум:

```text
symbol
+ timeframe
+ direction
+ sweep_timestamp
+ sweep_level
+ MSS/BOS timestamp
+ MSS/BOS level
```

Dedup должен в первую очередь ограничивать **повторную торговлю одним market event**, а уже потом учитывать OB.

**Приоритет: P1.**

---

# 4. Pattern Engine — Reversal

Reversal:

```text
Sweep → Displacement → MSS → [OB/FVG] → Entry
```

MSS является главным structural confirmation. Направление определяется MSS. [Источник: раздел 6]

## Это концептуально правильно

Самая сильная часть pipeline — не считать sweep сам по себе сигналом. Sweep должен быть связан с последующим structural shift.

## Но есть спорный порог displacement

В документации одновременно присутствуют разные представления:

- `candle_quality.is_displacement`: body > 1.5 ATR;
- MSS classification использует собственную displacement-логику;
- отдельный reversal displacement gate может использовать `has_displacement`. [Источник: разделы 6–7, 19]

### Рекомендация

MIMO должна проверить, что:

```text
candle_quality displacement
```
и
```text
structure MSS displacement
```

не означают разные вещи случайно.

Нужно явно разделить:

```text
structural_mss_displacement
execution/displacement_strength
```

Если это разные метрики — оставить обе, но не называть их одним термином.

**Приоритет: P1 для code review, не менять threshold без данных.**

---

# 5. Pattern Engine — Continuation

Continuation:

```text
Trend → Pullback → BOS → [OB/FVG] → Entry
```

Условия: trend != ranging, есть BOS, BOS действительно ломает последний swing, направление BOS совпадает с trend. [Источник: раздел 6]

## Здесь архитектура в целом хорошая

BOS + trend alignment разумно использовать как structural validity.

Но обнаружена важная семантическая проблема confirmation score.

---

# 6. Confirmation Score — текущий порог подозрительно слабый

Формула:

```text
BOS = +2
FVG = +1
OB  = +1
minimum = 2
```

Следовательно:

```text
BOS only = 2 → PASS
BOS + FVG = 3 → PASS
BOS + OB = 3 → PASS
```

Это означает, что в continuation path `confirmation_min=2` **не является настоящим дополнительным confirmation gate**: сам обязательный BOS уже удовлетворяет порогу. Это прямо отмечено в текущем аудите. [Источник: раздел 6, строки о Confirmation Score и раздел 28]

## Важный вывод

Не следует автоматически повышать `2 → 3`.

Это всего лишь гипотеза.

Нужно сравнить минимум:

```text
score=2
score=3
score=4
```

по:

- expectancy;
- PF;
- MAE;
- MFE;
- outcome distribution;
- cost-adjusted expectancy.

### Рекомендация

Оставить текущий `2` до получения outcome dataset.

**Приоритет: P0 для измерения, P1 для изменения.**

---

# 7. Entry Armed — не превращать в hard gate без статистики

`entry_armed` — soft state. Price должен быть близко к OB midpoint либо находиться внутри соответствующего FVG; текущий threshold — около 2%. [Источник: раздел 6]

В audit snapshot entry_armed встречается только у части detected signals.

## Важная идея

`entry_armed` и `entry_trigger` — разные понятия.

```text
entry_armed
= setup location is nearby

entry_trigger
= сейчас есть условия для реального входа
```

Это разделение сохранять.

---

# 8. Entry zone / proximity — потенциально сомнительный параметр

В текущей логике фигурирует proximity около 2% в описании entry zone; config registry также содержит feature flag `require_entry_zone=false`. [Источник: разделы 6–7, 25]

2% является абсолютной величиной и поэтому зависит от:

- symbol;
- volatility;
- timeframe;
- regime.

### Но менять 2% прямо сейчас не следует

Правильный эксперимент:

```text
distance_pct
normalized_distance = distance / ATR
```

и сравнить статистику по бинам:

```text
0–0.25 ATR
0.25–0.5 ATR
0.5–1 ATR
1–1.5 ATR
>1.5 ATR
```

Только потом определить adaptive proximity.

**Приоритет: P2.**

---

# 9. OB Retest — один из главных кандидатов на исследование

Текущий hard gate при `require_ob_retest=true` требует:

1. корректный возраст;
2. OB не broken/mitigated;
3. touch OB;
4. confirmation candle — engulfing или pin-bar. [Источник: раздел 7]

## Оценка

С точки зрения идеи ICT это разумно, но с точки зрения системного поиска это может быть слишком строгим conjunction:

```text
valid OB
AND
correct retest
AND
candle confirmation
```

### Важно

Не удалять hard invalidation:

```text
OB_BROKEN
OB_MITIGATED
wrong direction
```

А вот:

```text
OB_NOT_RETESTED
OB_NO_CONFIRMATION
```

исследовать как quality features.

### Рекомендуемый будущий split

```text
Hard:
    OB valid
    OB not broken
    correct direction

Soft:
    retest depth
    reaction speed
    engulfing
    pinbar
    penetration depth
```

Но делать split только после outcome/counterfactual analysis.

**Приоритет: P1.**

---

# 10. Session filter

`session_hard_gate=false` по умолчанию. Sessions используются как soft/context. [Источник: раздел 7 и config registry]

Это текущее решение я считаю **правильным**.

Не включать session hard gate только потому, что стратегия ICT обычно привязывает входы к определённым периодам.

Сначала собрать:

```text
London
Overlap
New York
Asian
Off-hours
```

и посчитать:

```text
N
expectancy
PF
MAE
MFE
average duration
```

по каждому setup type.

Важная деталь: session effect может отличаться для reversal и continuation.

---

# 11. HTF Bias — сейчас слишком жёсткая часть системы

HTF V2 анализирует W1/D1/H4/H1 и при bullish HTF блокирует short, при bearish — long. Continuation и reversal также должны совпадать с HTF direction. [Источник: раздел 16]

## Проблема

Это превращает HTF bias из context в hard veto.

Для continuation это вполне логично.

Для reversal — может быть неверно.

Пример:

```text
HTF bullish
↓
price reaches HTF premium / liquidity
↓
LTF sell-side sweep
↓
bearish MSS
↓
reversal SHORT
```

Если HTF bias всегда блокирует short, именно HTF context, который должен помочь определить location, становится причиной отказа.

### Рекомендация для будущей архитектуры

Разделить:

```text
Continuation:
    HTF mismatch = hard/strong penalty

Reversal:
    HTF mismatch + HTF POI = allowed with additional evidence
    HTF mismatch without POI = strong penalty
```

Не фиксировать численные веса заранее.

**Приоритет: P1.**

---

# 12. HTF POI — сильный недоиспользованный компонент

Trade Engine уже получает HTF POI, но текущее описание использует его прежде всего для SL override. В отдельном HTF анализе есть D1/H4/W1 OB/FVG. [Источник: разделы 8 и 16]

### Рекомендация

Сделать HTF POI частью location model:

```text
HTF POI
→ premium/discount/location
→ LTF liquidity event
→ MSS/BOS
→ entry
```

Это лучше, чем использовать HTF только как direction filter.

Но конкретная реализация должна учитывать фактический размер POI и distance нормализованный через ATR.

**Приоритет: P1.**

---

# 13. Trade Engine — сильная часть, но entry selection нужно исследовать отдельно

Trade Engine работает по liquidity-first логике:

```text
liquidity map
→ idea
→ invalidation
→ targets
→ RR
→ entry
```

Это хорошая концепция. [Источник: раздел 8]

## SL

SL строится от structural invalidation + 0.35 ATR buffer; при близком HTF POI может использовать HTF override.

Это предпочтительнее фиксированного процента, потому что SL имеет structural meaning.

### Что нужно проверить

Не менять 0.35 ATR вслепую.

Собрать распределения:

```text
MAE in ATR
MAE in %
stop distance / ATR
```

и посмотреть, сколько сделок выбивает до движения в правильную сторону.

---

# 14. Dynamic SL max — проблема исходно была реальной, но текущую формулу нужно считать гипотезой

Текущая формула:

```text
dynamic_sl_max = max(5%, ATR × 2.2)
dynamic_sl_max = min(dynamic_sl_max, 8%)
```

[Источник: раздел 11 и config description]

Она действительно устраняет старую dead zone между:

```text
SL >= 2 ATR
SL <= 5%
```

для ATR выше 2.5%.

Однако сама формула `ATR × 2.2` и cap 8% **не доказаны статистикой**.

### Правильный статус

```text
Dead-zone bug: FIXED
Final SL max model: NOT PROVEN
```

Не заменять сейчас 2.2 на 2.0/2.5/3.0 без MAE analysis.

---

# 15. Probability Engine — главный методологический риск

Rules-based probability начинается примерно с 50% и добавляет/уменьшает score по sweep, displacement, MSS/BOS, OB, FVG, volume, MTF, session, ATR, context, regime и soft multipliers. [Источник: раздел 10]

## Проблема 1: ручной score ≠ calibrated probability

Например:

```text
55.0%
```

не следует считать реальной вероятностью TP, пока не показано, что в bucket около 55% фактически закрывается TP примерно в 55% случаев.

Поэтому до calibration:

```text
p_tp = heuristic score
```

лучше трактовать как **ranking score**, а не точную вероятность.

---

# 16. Probability Engine — отсутствие RR в scoring является правильным решением

Текущая версия удаляет RR из probability scoring. Это следует сохранить.

RR должен входить в economics после оценки probability:

```text
P(TP)
+
RR / costs
↓
Expected Return
```

а не:

```text
RR
→ повышает P(TP)
```

Это было одной из ключевых правильных модификаций предыдущего этапа.

---

# 17. EV — текущую формулу нужно унифицировать с costs

В текущем аудите:

```text
expected_net_r = p*b - (1-p)
```

и Risk Engine рассчитывает effective RR через fees + slippage. [Источник: разделы 10–11]

## Требование к MIMO

Нужно строго определить, что такое `b` в каждом месте кода:

### Вариант A

```text
gross_RR
+ explicit transaction cost
→ net EV
```

### Вариант B

```text
effective_RR (costs already included)
→ EV
```

Нельзя одновременно использовать effective RR и ещё раз вычитать те же costs.

**Приоритет: P0 code audit.**

---

# 18. `min_p_tp` — сейчас это legacy gate, а не качественный economic decision

Текущие thresholds:

```text
BUY       0.30
SELL      0.40
REVERSAL  0.50
```

[Источник: раздел 10 и config registry]

При наличии `EV <= 0` hard gate и calibrated probability в будущем отдельные fixed P(TP) thresholds становятся вторичными.

### Рекомендация

Не менять thresholds только на основании intuition.

Постепенно перейти к:

```text
calibrated P(TP)
+
net/effective RR
+
costs
+
required edge
↓
EV decision
```

При этом fixed minimum P(TP) можно временно оставить как safety guard.

**Приоритет: P1 архитектурный.**

---

# 19. Risk Engine — сильная часть, но Kelly сейчас не работает так, как может казаться

Текущий Kelly режим:

```text
kelly = (p*b-q)/b
kelly = min(kelly, 0.20)
kelly *= confidence
risk_pct = min(kelly*100, base_risk_pct)
```

При `base_risk_pct=1%` Kelly **не может повысить риск выше 1%**. Он только снижает fixed risk. Это прямо отмечено в current audit. [Источник: раздел 11 и раздел 28]

### Это не обязательно баг

Это может быть сознательный risk ceiling.

Но название `risk_mode=kelly` может создавать ложное ожидание полноценного Kelly sizing.

### Рекомендация

До calibration оставить `fixed` 1%.

После calibration проверить:

```text
fractional Kelly
× confidence
× max portfolio risk
× daily risk cap
```

и только потом разрешать Kelly увеличивать размер.

Не поднимать `max_risk_pct` просто ради того, чтобы «Kelly заработал».

**Приоритет: P1.**

---

# 20. Risk limits — есть конфигурационная несогласованность

В `TradingConfig` указан:

```text
min_rr_threshold = 1.5
```

но Risk Engine реально блокирует:

```text
min_rr_ratio = 2.0
```

[Источник: раздел 25 и раздел 11]

Это не обязательно runtime bug, но это **опасная ambiguity**.

### MIMO должна сделать

Найти все использования:

```text
min_rr_threshold
min_rr_ratio
RISK_ENGINE_MIN_RR
```

и установить один canonical parameter.

Если `min_rr_threshold` legacy и не используется — удалить его только после подтверждения grep/call-site analysis.

**Приоритет: P0 code consistency.**

---

# 21. Volatility Filter — не оптимизировать по одному числу

Текущий hard filter:

```text
ATR < 0.3% → reject
ATR > 5%   → reject
```

[Источник: раздел 5]

Сам по себе фильтр разумен как safety guard, но 5% не является доказанным универсальным пределом.

Не следует менять его прямо сейчас.

### После накопления данных

Исследовать:

```text
ATR percentile
ATR / rolling ATR
ATR regime
ATR + setup type
ATR + session
ATR + SL/ATR
```

Возможно, percentile-based regime окажется устойчивее фиксированных процентов.

**Приоритет: P2.**

---

# 22. Sweep filters — потенциально важный источник systematic bias

Текущие параметры:

```text
max_body_beyond_level = 0.3 ATR
min_wick_beyond_level = 0.1%
min_body_size = 0.05%
max_pool_age_bars = 100
lookback = 50
```

[Источник: раздел 19]

### Что здесь подозрительно

Эти параметры смешивают:

- абсолютные проценты;
- ATR-relative distance;
- количество баров.

То есть одна и та же логика ведёт себя по-разному для разных symbol/TF/regime.

### Но менять сейчас нельзя

Сначала нужен counterfactual outcome data:

```text
accepted sweep
vs
filtered sweep
```

с forward outcome.

Особенно важно проверить:

```text
sweep direction
sweep strength
pool age
reclaim candles
```

**Приоритет: P2 после live dataset.**

---

# 23. OB age — параметр не нормализован по TF

OB хранит candle index/timestamp и имеет age/retest/mitigation state. [Источник: раздел 19]

Если возраст задаётся количеством свечей, то одинаковое значение на 1h и 4h означает разный elapsed time.

### Рекомендация

Не просто заменить на 36 часов.

Сравнить:

```text
age in candles
age in hours
number of retests
mitigation depth
age / ATR regime
```

И выбрать критерий, который действительно коррелирует с edge.

**Приоритет: P2.**

---

# 24. Premium / Discount

`premium_discount=false` по умолчанию. Текущий audit указывает, что предыдущее A/B сравнение дало ухудшение PF примерно с 1.28 до 0.91. [Источник: раздел 28]

## Мой вывод

**Не включать сейчас.**

Но и удалять компонент нельзя.

Сначала проверить:

1. какой dealing range использовался;
2. его anchor;
3. какой timeframe;
4. одинаково ли считалась premium/discount для long и short;
5. не было ли leakage или look-ahead;
6. сколько наблюдений в A/B.

После этого повторить OOS experiment.

---

# 25. HTF Bias — проблема с `block_neutral_htf`

Конфиг:

```text
block_neutral_htf = true
```

но текущий audit утверждает, что neutral HTF всегда пропускается. [Источник: раздел 28]

Это **подозрительная feature-contract inconsistency**.

### Требование

Проверить реальный путь:

```text
block_neutral_htf
→ htf_bias_v2
→ scanner
```

и сделать только одно из двух:

- либо флаг реально работает;
- либо flag/documentation приводится в соответствие.

Не оставлять dead config option.

**Приоритет: P0 code consistency.**

---

# 26. HTF Bias V2 confidence — не считать confidence статистической вероятностью

Текущая формула:

```text
confidence = min(|EMA21-EMA55| / price × 100 × 10, 100)
```

В документации правильно указано, что это **не statistical confidence**. [Источник: раздел 16]

MIMO не должна использовать это число как:

```text
probability
confidence interval
model certainty
```

Если оно влияет на score/risk, его следует назвать более точно, например `htf_strength_score`.

**Приоритет: P1 naming/semantic clarity.**

---

# 27. Context Fetcher singleton state

`ContextFetcher` хранит внутреннее state: F&G cache, trending cache, RSS cache, last OI. [Источник: раздел 1 и раздел 28]

Это не обязательно production bug, но потенциальный источник:

- stale context;
- test contamination;
- order-dependent outcomes.

### Требование к MIMO

Проверить:

```text
cache TTL
cache key
symbol isolation
exception recovery
```

и убедиться, что snapshot timestamp записывается вместе с features.

**Приоритет: P1.**

---

# 28. Candle close discipline — оставить без изменений

`fetch_ohlcv` отбрасывает последний открытый бар. Это правильный safety rule против signal-on-forming-candle. [Источник: раздел 5 и раздел 28]

Не менять.

При любых будущих изменениях data pipeline обязательно сохранить правило:

```text
NO LIVE UNFINISHED CANDLE IN SIGNAL FEATURES
```

И в audit log хранить:

```text
as_of_utc
bar_close_timestamp
scan_timestamp
```

---

# 29. Indicators — не превращать их в hard gates без доказательства

Текущие индикаторы:

- EMA 8/21/55;
- RSI 10;
- MACD 8/21/5;
- ADX/DMI 14;
- ATR 14;
- Supertrend 10/2.5;
- Volume SMA 20.

Они не блокируют setup, а в основном используются как features. [Источник: раздел 18]

Это хорошее решение.

### Не рекомендуется

Добавлять:

```text
RSI > X
ADX > Y
MACD > 0
```

как hard ICT gates.

Это может превратить structural strategy в generic indicator strategy и увеличить overfitting.

---

# 30. Volume scoring — проверить двойной учёт

Volume используется как feature и в rules-based scoring.

Проверить, не возникает ли такой цепочки:

```text
sweep strength
→ учитывает high_volume

volume_ratio
→ снова получает bonus
```

Если одно и то же observable event входит в разные score terms, edge может быть посчитан дважды.

Это не доказанная ошибка, а **feature-dependency risk**.

**Приоритет: P1 analysis.**

---

# 31. SMT — пока только soft feature

SMT возвращает direction/detail и score [-1,1]. [Источник: раздел 20]

Оставить soft.

После накопления данных отдельно оценить:

```text
SMT present vs absent
SMT aligned vs opposite
reversal vs continuation
```

Не делать hard gate только потому, что SMT теоретически считается сильным ICT confirmation.

---

# 32. Breakout Quality — сохранить в текущем режиме

BreakoutQuality классифицирует breakout как real/fake и по умолчанию hard gate выключен. [Источник: раздел 7]

Это хороший кандидат для counterfactual study.

Особенно полезно сравнить:

```text
breakout score
vs
subsequent continuation probability
```

Не включать hard gate автоматически.

---

# 33. Outcome Definition — обязательный контракт для дальнейшей ML/EV работы

Для каждого сигнала и counterfactual trade должна быть однозначно определена outcome label.

Минимум:

```text
HIT_TP
HIT_SL
EXPIRED
```

как уже используется outcome tracker. Но для исследовательского слоя необходимо также хранить:

```text
entry_timestamp
entry_price
sl_price
initial_tp_price
exit_timestamp
exit_price
bars_to_exit
MAE
MFE
gross_R
net_R
fees
slippage
funding (если relevant)
```

Иначе probability calibration и EV будут недостаточно воспроизводимыми.

**Приоритет: P0 для дальнейшей calibration.**

---

# 34. Counterfactual engine — что должен делать

Нужен отдельный `hypothetical_trade_engine` для blocked signals.

Он **не должен участвовать в live decision path**.

Правильная схема:

```text
LIVE SCANNER
    ↓
AUDIT SNAPSHOT
    ↓
BLOCKED
    ↓
HYPOTHETICAL REPLAY
```

Не:

```text
scanner
→ hypothetical engine
→ live trade decision
```

## Три уровня counterfactual

### Level 1 — gate-only

Убрать один gate, остальные условия оставить без изменений.

### Level 2 — pipeline replay

После снятия gate продолжить pipeline до следующего решения.

### Level 3 — execution replay

Пересчитать entry / SL / TP / RR так, как реально работала бы альтернативная стратегия.

Для окончательных решений использовать Level 3.

---

# 35. Counterfactual interactions — обязательный анализ

Нельзя делать вывод:

```text
Gate X плохо → Gate X удалить
```

только по одиночному снятию X.

Нужны interaction tests:

```text
HTF × MSS
OB × MSS
SMT × reversal
session × setup_type
displacement × volatility
confirmation × continuation
```

Потому что feature может быть слабой сама по себе, но сильной в комбинации.

---

# 36. Walk-forward validation — обязательна

Никаких random train/test split для временных market observations.

Использовать:

```text
Train
→ Calibration
→ Forward/OOS
→ Roll window
→ Repeat
```

Для probability model проверять:

- Brier score;
- LogLoss;
- calibration curve;
- OOS expectancy;
- stability between periods.

---

# 37. Конфигурация — кандидаты на проверку

## P0 / contract consistency

```text
min_rr_threshold = 1.5
vs
RiskEngine.min_rr_ratio = 2.0
```

```text
block_neutral_htf = true
vs
neutral HTF behavior = pass
```

```text
reason code count: 46/47 documentation mismatch
```

Проверить и унифицировать.

## P1 / strategy behavior

```text
confirmation_min = 2
require_ob_retest = true
htf_hard_gate = true
block_short_in_bullish_htf = true
block_long_in_bearish_htf = true
```

Не менять до outcome analysis.

## P2 / parameter research

```text
volatility 0.3–5.0%

sweep thresholds
OB age
OB proximity
0.35 ATR SL buffer
ATR × 2.2 dynamic SL max
TP ATR multipliers
```

---

# 38. Risk limits — текущие значения

Текущая конфигурация включает:

```text
base risk             1.0%
max risk/day          6.0%
max trades/day        5
max positions         5
max active signals    10
max portfolio risk    3.7%
consecutive losses    3
```

[Источник: раздел 21]

## Оценка

Это относится к **risk policy**, а не к edge discovery.

Не следует подстраивать эти параметры под win rate.

Особенно не надо повышать дневной или portfolio risk только из-за хорошей текущей серии.

Для production риск должен оставаться консервативным до получения устойчивой OOS статистики.

---

# 39. Execution — текущие hard filters

```text
spread <= 0.15%
depth >= $10,000 within 0.5%
correlated entry = blocked
```

[Источник: раздел 15]

## Оценка

Это полезные защитные фильтры, но thresholds зависят от:

- exchange;
- symbol;
- market session;
- volatility;
- notional size.

### Будущая оптимизация

Вместо фиксированного `$10k` исследовать depth относительно:

```text
planned order notional
```

Например:

```text
available depth / order notional
```

Это гораздо устойчивее.

Пока не менять.

---

# 40. TOCTOU и atomic save — сохранять

Повторная portfolio check перед записью и atomic этап сохранения/обновления outcome/daily limits/cooldown — хорошие инженерные меры. [Источник: раздел 15]

Не удалять.

---

# 41. Что сейчас считать доказанно исправленным

По предоставленному audit:

1. RR feedback loop устранён.
2. Min-notional dimension исправлена.
3. Expected RR / Profit Factor formulas исправлены.
4. SL dead-zone устранена технически.
5. Последняя открытая свеча исключается.
6. Decision/audit trace расширен.
7. 53 features пишутся в trace.
8. Analytical overlays отделены от hard shadow logic.

[Источник: changelog и соответствующие разделы]

Эти исправления **не нужно откатывать**, кроме случаев, когда новый live/outcome data прямо докажет регрессию.

---

# 42. Приоритетный backlog для MIMO v2.5

## P0 — проверить до стратегического тюнинга

### P0.1 Canonical RR parameter

Найти все `min_rr_threshold`, `min_rr_ratio` и оставить один источник истины.

### P0.2 EV cost semantics

Установить однозначный контракт:

```text
gross RR
или
net/effective RR
```

без double counting costs.

### P0.3 Neutral HTF flag

Проверить `block_neutral_htf`; устранить dead config behavior.

### P0.4 Outcome contract

Унифицировать TP/SL/EXPIRED/MAE/MFE/net-R labeling.

### P0.5 Audit reason-code registry

Синхронизировать фактическое количество codes и документацию.

---

# 43. P1 — исследования, не немедленные изменения

1. Confirmation score `2` vs `3`.
2. OB retest hard vs hybrid.
3. HTF Bias для reversal.
4. HTF POI как location.
5. OB-aware event dedup.
6. Kelly semantics.
7. Context cache behavior.
8. Feature dependency / double counting.
9. Breakout Quality effectiveness.
10. LTF confirmation impact.

---

# 44. P2 — параметрическая оптимизация после накопления данных

1. Sweep thresholds.
2. Sweep pool age.
3. OB age.
4. OB proximity.
5. FVG thresholds.
6. 0.35 ATR SL buffer.
7. dynamic SL max multiplier.
8. ATR volatility limits.
9. TP ATR multipliers.
10. session weighting.
11. SMT weights.
12. premium/discount definition.
13. execution depth threshold.

---

# 45. Какие показатели использовать

## Primary

```text
Net Expectancy (R/trade)
Profit Factor
Max Drawdown
OOS Expectancy
MAE
MFE
Cost-adjusted return
```

## Probability

```text
Brier Score
LogLoss
Calibration Curve
Reliability / predicted vs actual
```

## Diagnostics

```text
Gate block rate per gate
Counterfactual expectancy
Interaction effect
Sample size
Confidence interval
```

## Не использовать как primary objective

```text
Win rate > 50%
Rejection rate < X%
Количество сигналов
```

Высокий win rate без достаточного RR может быть плохой стратегией; низкий rejection rate сам по себе тоже не является целью.

---

# 46. Минимальная таблица эксперимента

Для каждого исследуемого gate/параметра сохранять:

| Поле | Значение |
|---|---|
| hypothesis_id | H-xxx |
| config_version | xxx |
| symbol | BTC/USDT |
| timeframe | 1h |
| setup_type | reversal/continuation |
| gate | название |
| baseline_state | pass/block |
| counterfactual_state | pass/block |
| entry | price |
| SL | price |
| TP | price |
| RR | value |
| P(TP) | calibrated/un-calibrated |
| gross_R | result |
| net_R | result after cost |
| MAE | value |
| MFE | value |
| outcome | TP/SL/EXPIRED |
| period | OOS period |

---

# 47. Правила изменения кода для MIMO v2.5

### Rule 1
Не менять несколько независимых групп параметров одним commit.

### Rule 2
Каждое изменение стратегии получает новый `config_version`.

### Rule 3
Каждый параметр имеет baseline и hypothesis id.

### Rule 4
Нельзя удалять audit reason codes, если они уже используются журналом.

### Rule 5
Не удалять существующие features только потому, что они пока не используются как hard gates.

### Rule 6
Не переводить soft feature в hard gate без counterfactual evidence.

### Rule 7
Не переводить hard structural gate в soft score без evidence, что это улучшает OOS expectancy.

### Rule 8
Любой ML/calibration experiment должен быть temporal/OOS.

### Rule 9
Нельзя оптимизировать параметры по одной серии wins/losses.

### Rule 10
Не менять live baseline, если изменение не относится к доказанному bug/contract inconsistency.

---

# 48. Рекомендуемая целевая архитектура

После накопления достаточного outcome data целевая модель должна выглядеть так:

```text
MARKET DATA
    │
    ├── HTF CONTEXT
    │      ├── HTF POI
    │      ├── HTF structure
    │      └── premium/discount
    │
    └── LTF STRUCTURE
           ├── Sweep
           ├── MSS
           └── BOS

          ↓

STRUCTURAL SETUP
    │
    └── minimal hard structural gates

          ↓

SETUP QUALITY
    ├── OB/FVG quality
    ├── displacement strength
    ├── session
    ├── volume
    ├── SMT
    ├── regime
    └── HTF context

          ↓

CALIBRATED P(TP)
          │
          ↓
ENTRY / SL / TP MODEL
          │
          ↓
NET EXPECTED VALUE
          │
          ↓
RISK SIZING
          │
          ↓
LTF ENTRY TRIGGER
          │
          ↓
EXECUTION
```

Главное правило: **Setup Quality не равен Entry Trigger, а P(TP) не равен Expected Value.**

---

# 49. Финальный порядок работы

## Сейчас

**Freeze baseline.**

Продолжать live data collection на одной версии стратегии.

Параллельно завершить только технические P0 audit items и synthetic/hypothetical trade engine.

## После достаточной выборки

```text
Live outcomes
    ↓
Gate effectiveness
    ↓
Counterfactual replay
    ↓
Interaction analysis
    ↓
Architecture changes
    ↓
Calibration
    ↓
OOS validation
    ↓
Parameter optimization
```

---

# 50. Финальная независимая оценка

Бот не выглядит как набор случайных индикаторных правил. Это уже полноценная многоуровневая исследовательско-торговая система с ICT structural core, liquidity model, probability/risk layers и auditability.

Основной риск сейчас — не отсутствие новых индикаторов и не недостаток фильтров. Наоборот: главный риск — **избыточная жёсткость некоторых gates и возможное повторное взвешивание одной и той же информации в разных слоях**.

На текущем этапе наиболее правильная стратегия разработки:

```text
НЕ добавлять больше сигналов
НЕ ослаблять фильтры на глаз
НЕ оптимизировать десятки параметров сразу

СНАЧАЛА:
    сохранить чистый baseline
    собрать outcomes
    построить counterfactual replay
    измерить gate-level expectancy
    измерить MAE/MFE
    откалибровать probability

ПОТОМ:
    менять архитектуру по доказанному edge
```

### Приоритет для MIMO v2.5

```text
P0 = code-contract/data-integrity correctness
P1 = structural/architectural research
P2 = numerical parameter optimization
```

**Главная рекомендация:** не считать текущие `2`, `2.2`, `5%`, `8%`, `0.35 ATR`, `0.15% spread`, `$10k depth`, `OB age`, `2% proximity` и другие числа «правильными» просто потому, что они работают. Это baseline hypotheses, пока они не подтверждены OOS статистикой.

---

## Source basis

Этот документ подготовлен на основе предоставленного полного аудита `bot_audit(1).md`, версии 2.5.0 от 2026-09-08, включая описание pipeline, runtime config, reason codes, risk engine, probability engine, HTF logic, liquidity detectors, audit logging и известные проблемы.
