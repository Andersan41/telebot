"""
monitoring/metrics.py — Prometheus-метрики бота (T3.4).

Опциональный экспорт: включается переменной окружения METRICS_ENABLED=1.
HTTP-сервер слушает порт METRICS_PORT (по умолч. 9090).
"""
from prometheus_client import Counter, Histogram, start_http_server

signals_total = Counter(
    "tgbot_signals_total",
    "Сигналы, опубликованные ботом",
    labelnames=("signal_type", "symbol", "timeframe"),
)

scan_duration_seconds = Histogram(
    "tgbot_scan_duration_seconds",
    "Длительность одного scan_symbol",
    labelnames=("timeframe",),
)

context_fetch_errors_total = Counter(
    "tgbot_context_fetch_errors_total",
    "Ошибки в контекстном модуле",
    labelnames=("source",),
)


def _start_metrics_server() -> None:
    """Запускает HTTP-сервер для Prometheus-экспорта (opt-in)."""
    import os

    enabled = os.getenv("METRICS_ENABLED", "false").lower() == "true"
    if not enabled:
        return

    port = int(os.getenv("METRICS_PORT", "9090"))
    start_http_server(port)
