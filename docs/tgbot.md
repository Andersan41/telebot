# tgbot.md — Контекст проекта Telegram Trading Bot

## Цель проекта

Построить не просто торгового бота, а самоанализирующуюся торговую систему, которая фиксирует каждое решение, хранит причины его принятия, анализирует результаты и улучшает стратегию на основе данных, а не интуиции.

## Что было сделано

### 1. Переход от rule-based к data-driven подходу

Изначально бот был набором правил:

Market → Indicators → Signal Engine → Filters → Risk → Signal

Теперь цель — сохранять весь путь принятия решения и анализировать его.

### 2. Исторические исследования

Проведены исследования на датасете (~1138 сделок):

- Sweep analysis
- Correlation
- Logistic Regression
- Random Forest
- XGBoost
- SHAP
- LOFO
- Feature importance
- Regime analysis
- ADX analysis
- Interaction analysis

Основные выводы:

- DMI, EMA, ADX и Volume — сильные факторы.
- Sweep ухудшает SELL, но после контроля других факторов становится скорее индикатором плохих условий.
- Между признаками обнаружено большое количество дублирования.

### 3. DecisionTrace

Добавлен журнал каждого прохождения пайплайна.

Сохраняются:

- прохождение всех gate;
- место блокировки;
- причина;
- итог сделки;
- PnL.

Теперь можно построить Funnel, Counterfactual и Gate Analytics.

### 4. Feature Snapshot

Для каждого решения сохраняется состояние рынка:

ADX, RSI, EMA, MACD, DMI, Volume, Regime, Direction, Score, Confidence, SL, TP, RR, BOS, Sweep, OB, Context, BTC trend, MTF и др.

### 5. Signal Candidates

Логируются все вызовы evaluate(), даже если сигнал не был создан.

Получается полный ML-датасет:

рынок → решение → результат.

### 6. Outcome Linking

Каждый Candidate связывается с итогом сделки:

TP / SL / EXPIRED / PnL.

### 7. Decision Intelligence

Развитие системы направлено на создание аналитического слоя:

- config_snapshot;
- strategy_version;
- feature snapshot;
- gate analytics;
- counterfactual;
- weekly audit;
- drift detection;
- version comparison.

### 8. Gate Analytics

Для каждого gate вычисляются:

- entered;
- passed;
- dropped;
- downstream WR;
- PF;
- expectancy;
- counterfactual.

### 9. Counterfactual

Главный принцип:

Не спрашивать "сколько сделок заблокировал gate",

а спрашивать

"что произойдёт, если его убрать?"

### 10. Drift Detection

Планируется автоматический контроль деградации стратегии по неделям.

### 11. Weekly Audit

Автоматический отчёт:

- WR;
- PF;
- лучшие и худшие gate;
- drift;
- рекомендации.

### 12. Version Comparison

Каждое решение должно хранить:

- версию стратегии;
- конфигурацию;
- параметры.

Это позволит сравнивать версии стратегии автоматически.

### 13. Проверка дублирования gate

Обнаружены возможные дубли и конфликты.

Решение:

ничего не удалять до статистического подтверждения через DecisionTrace.

### Финальная цель

Rule-based стратегия остаётся ядром.

DecisionTrace становится памятью системы.

Feature Snapshot описывает состояние рынка.

Counterfactual проверяет гипотезы.

Gate Analytics показывает эффективность фильтров.

ML используется как дополнительный слой оценки вероятности успеха, а не как замена стратегии.
