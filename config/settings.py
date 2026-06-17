"""
config/settings.py — Централизованная конфигурация бота

Все пороги, веса и параметры — в одном месте. Горячая перезагрузка через
`reload_config()` (перечитывает .env и пересоздаёт singleton без рестарта).
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TelegramConfig:
    """Параметры Telegram-бота."""

    # Токен бота для авторизации API-запросов
    token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    # ID канала для публикации сигналов
    channel_id: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
    # Список ID администраторов (через запятую)
    admin_ids: List[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()
    ])
    # ID канала для логов ошибок
    error_channel_id: str = os.getenv("TELEGRAM_ERROR_CHANNEL_ID", "")


@dataclass
class ExchangeConfig:
    """Параметры подключения к бирже."""

    # Название биржи (по умолчанию bingx)
    name: str = os.getenv("EXCHANGE", "bingx")
    # API-ключ биржи (читаем из универсального EXCHANGE_API_KEY или бирже-специфичного)
    api_key: str = os.getenv("EXCHANGE_API_KEY", "") or os.getenv("BINANCE_API_KEY", "")
    # API-секрет биржи
    api_secret: str = os.getenv("EXCHANGE_API_SECRET", "") or os.getenv("BINANCE_API_SECRET", "")
    # Использовать ли тестнет
    testnet: bool = os.getenv("USE_TESTNET", "false").lower() == "true"
    # Тип рынка: spot / future / swap (swap = perpetual futures для BingX/Bybit)
    market_type: str = os.getenv("MARKET_TYPE", "swap")


@dataclass
class TradingConfig:
    """Параметры торговли и индикаторов."""

    # Список инструментов для сканирования (через запятую)
    symbols: List[str] = field(default_factory=lambda: [
        s.strip() for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")
    ])
    # Основные таймфреймы для сканирования
    primary_timeframes: List[str] = field(default_factory=lambda: [
        tf.strip() for tf in os.getenv("PRIMARY_TIMEFRAMES", "1h,4h").split(",")
    ])
    # Таймфрейм подтверждения сигнала
    confirm_timeframe: str = os.getenv("CONFIRM_TIMEFRAME", "15m")
    # Включить подтверждение на confirm_timeframe
    confirm_tf_enabled: bool = os.getenv("CONFIRM_TF_ENABLED", "true").lower() == "true"

    # ─── EMA ─────────────────────────────────────────────────────────────
    # Период быстрой EMA
    ema_fast: int = int(os.getenv("EMA_FAST", "8"))
    # Период медленной EMA
    ema_slow: int = int(os.getenv("EMA_SLOW", "21"))
    # Период трендовой EMA
    ema_trend: int = int(os.getenv("EMA_TREND", "55"))
    # Минимальный % разницы между EMA fast/slow (фильтр)
    min_ema_spread_pct: float = float(os.getenv("MIN_EMA_SPREAD_PCT", "0.20"))
    # Включить проверку наклона EMA fast (отключена по умолчанию — слишком жёсткий фильтр)
    ema_slope_check: bool = os.getenv("EMA_SLOPE_CHECK", "false").lower() == "true"
    # Коэффициент нормализации EMA spread strength (1.0 = max strength при spread >= 1%)
    ema_strength_cap: float = float(os.getenv("EMA_STRENGTH_CAP", "1.0"))

    # ─── RSI ─────────────────────────────────────────────────────────────
    # Период RSI
    rsi_period: int = int(os.getenv("RSI_PERIOD", "10"))
    # Уровень перекупленности RSI
    rsi_overbought: float = float(os.getenv("RSI_OVERBOUGHT", "72"))
    # Уровень перепроданности RSI
    rsi_oversold: float = float(os.getenv("RSI_OVERSOLD", "28"))
    # Минимальный RSI для бычьей зоны
    rsi_bull_min: float = float(os.getenv("RSI_BULL_MIN", "55"))
    # Максимальный RSI для медвежьей зоны
    rsi_bear_max: float = float(os.getenv("RSI_BEAR_MAX", "45"))

    # ─── MACD ────────────────────────────────────────────────────────────
    # Период быстрой линии MACD
    macd_fast: int = int(os.getenv("MACD_FAST", "8"))
    # Период медленной линии MACD
    macd_slow: int = int(os.getenv("MACD_SLOW", "21"))
    # Период сигнальной линии MACD
    macd_signal: int = int(os.getenv("MACD_SIGNAL", "5"))
    # Минимальный % MACD гистограммы от цены (фильтр шума)
    min_macd_pct: float = float(os.getenv("MIN_MACD_PCT", "0.03"))
    # Множитель MACD raw score
    macd_score_multiplier: float = float(os.getenv("MACD_SCORE_MULTIPLIER", "10"))
    # Включить проверку наклона MACD гистограммы (отключена по умолчанию — слишком жёсткий фильтр)
    macd_slope_check: bool = os.getenv("MACD_SLOPE_CHECK", "false").lower() == "true"

    # ─── ADX / DMI ───────────────────────────────────────────────────────
    # Период ADX
    adx_period: int = int(os.getenv("ADX_PERIOD", "14"))
    # Минимальный ADX для тренда (фильтр флэта)
    adx_min: float = float(os.getenv("ADX_MIN", "20"))
    # Порог ADX для strong trend
    adx_strong: float = float(os.getenv("ADX_STRONG", "22"))
    # Диапазон нормализации ADX strength (ADX_MIN → 0, ADX_MIN+30 → 1)
    adx_strength_range: float = float(os.getenv("ADX_STRENGTH_RANGE", "30"))
    # Делитель нормализации DMI diff
    dmi_norm_divisor: float = float(os.getenv("DMI_NORM_DIVISOR", "50"))
    # Множитель DMI strength
    dmi_strength_multiplier: float = float(os.getenv("DMI_STRENGTH_MULTIPLIER", "2"))

    # ─── ATR ─────────────────────────────────────────────────────────────
    # Период ATR
    atr_period: int = int(os.getenv("ATR_PERIOD", "14"))
    # Множитель ATR для Stop Loss
    atr_multiplier_sl: float = float(os.getenv("ATR_MULTIPLIER_SL", "1.5"))
    # Множитель ATR для Take Profit
    atr_multiplier_tp: float = float(os.getenv("ATR_MULTIPLIER_TP", "3.0"))
    # Fallback ATR = close * atr_fallback_pct (если ATR = 0)
    atr_fallback_pct: float = float(os.getenv("ATR_FALLBACK_PCT", "2.0"))

    # ─── Supertrend ──────────────────────────────────────────────────────
    # Период Supertrend
    supertrend_period: int = int(os.getenv("SUPERTREND_PERIOD", "10"))
    # Множитель Supertrend
    supertrend_multiplier: float = float(os.getenv("SUPERTREND_MULTIPLIER", "2.5"))

    # ─── Volume ──────────────────────────────────────────────────────────
    # Множитель объёма выше SMA для фильтра
    volume_factor: float = float(os.getenv("VOLUME_FACTOR", "1.5"))
    # Период SMA объёма
    volume_sma_period: int = int(os.getenv("VOLUME_SMA_PERIOD", "20"))
    # Порог бычьей дельты объёма (%)
    delta_bullish: float = float(os.getenv("DELTA_BULLISH", "15"))
    # Порог медвежьей дельты объёма (%)
    delta_bearish: float = float(os.getenv("DELTA_BEARISH", "-15"))
    # Делитель нормализации volume delta strength
    volume_delta_norm: float = float(os.getenv("VOLUME_DELTA_NORM", "50"))
    # Множитель объёма для compression breakout (выше стандартного volume_factor)
    compression_volume_factor: float = float(os.getenv("COMPRESSION_VOLUME_FACTOR", "2.0"))

    # ─── Filter toggles (signal_engine gates) ──────────────────────────
    # ADX flat filter (NO_SIGNAL if ADX < adx_min)
    adx_filter_enabled: bool = os.getenv("ADX_FILTER_ENABLED", "true").lower() == "true"
    # EMA alignment gate (fast > slow > trend for BUY, reverse for SELL)
    ema_alignment_enabled: bool = os.getenv("EMA_ALIGNMENT_ENABLED", "true").lower() == "true"
    # EMA minimum spread gate
    ema_spread_enabled: bool = os.getenv("EMA_SPREAD_ENABLED", "true").lower() == "true"
    # Trigger gate (requires at least one trigger)
    trigger_required: bool = os.getenv("TRIGGER_REQUIRED", "true").lower() == "true"
    # Candle close confirmation (reject wick breakouts)
    candle_close_enabled: bool = os.getenv("CANDLE_CLOSE_ENABLED", "true").lower() == "true"
    # Minimum score gate
    min_score_enabled: bool = os.getenv("MIN_SCORE_ENABLED", "true").lower() == "true"
    # Compression breakout mode (stricter checks in compression regime)
    compression_enabled: bool = os.getenv("COMPRESSION_ENABLED", "true").lower() == "true"

    # ─── Candles ─────────────────────────────────────────────────────────
    # Лимит свечей при запросе OHLCV
    candles_limit: int = int(os.getenv("CANDLES_LIMIT", "200"))


@dataclass
class LiquidityConfig:
    """Параметры ликвидности: sweeps, order blocks, FVG, качество свечей."""

    # ─── Sweeps ──────────────────────────────────────────────────────────
    # Максимальное число свечей для reclaim после sweep
    sweep_max_reclaim_candles: int = int(os.getenv("SWEEP_MAX_RECLAIM_CANDLES", "2"))
    # Минимальное соотношение объёма sweep к среднему
    sweep_min_volume_ratio: float = float(os.getenv("SWEEP_MIN_VOLUME_RATIO", "1.8"))
    # Число свечей для «быстрого» reclaim (strength scoring)
    sweep_fast_reclaim_candles: int = int(os.getenv("SWEEP_FAST_RECLAIM_CANDLES", "3"))
    # Минимальное соотношение фитиля к телу для sweep
    sweep_min_wick_body_ratio: float = float(os.getenv("SWEEP_MIN_WICK_BODY_RATIO", "2.0"))
    # Lookback для поиска swing points при sweep detection
    sweep_lookback: int = int(os.getenv("SWEEP_LOOKBACK", "50"))
    # Окно для определения swing points
    sweep_swing_window: int = int(os.getenv("SWEEP_SWING_WINDOW", "5"))
    # Максимальное число свечей для проверки reclaim
    sweep_max_check_reclaim: int = int(os.getenv("SWEEP_MAX_CHECK_RECLAIM", "10"))
    # Максимальное число свечей для проверки displacement после sweep
    sweep_max_check_displacement: int = int(os.getenv("SWEEP_MAX_CHECK_DISPLACEMENT", "5"))
    # Порог delta для подтверждения направления sweep
    sweep_delta_aligned_threshold: float = float(os.getenv("SWEEP_DELTA_ALIGNED_THRESHOLD", "0.5"))

    # Sweep strength scoring increments
    sweep_strength_fast_reclaim: float = float(os.getenv("SWEEP_STRENGTH_FAST_RECLAIM", "0.3"))
    sweep_strength_high_volume: float = float(os.getenv("SWEEP_STRENGTH_HIGH_VOLUME", "0.3"))
    sweep_strength_delta_aligned: float = float(os.getenv("SWEEP_STRENGTH_DELTA_ALIGNED", "0.2"))
    sweep_strength_displacement: float = float(os.getenv("SWEEP_STRENGTH_DISPLACEMENT", "0.2"))

    # ─── Order Blocks ────────────────────────────────────────────────────
    # Минимальный % displacement для OB
    ob_min_displacement_pct: float = float(os.getenv("OB_MIN_DISPLACEMENT_PCT", "2.5"))
    # Минимальный ATR-нормализованный displacement для OB
    ob_min_displacement_atr: float = float(os.getenv("OB_MIN_DISPLACEMENT_ATR", "1.5"))
    # Минимальное соотношение объёма для OB
    ob_min_volume_ratio: float = float(os.getenv("OB_MIN_VOLUME_RATIO", "1.8"))
    # Максимальный возраст OB в свечах
    ob_max_age_candles: int = int(os.getenv("OB_MAX_AGE_CANDLES", "35"))
    # Требуется ли ретест для валидации OB
    ob_retest_required: bool = os.getenv("OB_RETEST_REQUIRED", "false").lower() == "true"
    # Lookback для поиска OB
    ob_lookback: int = int(os.getenv("OB_LOOKBACK", "100"))
    # Окно для swing detection в OB
    ob_swing_window: int = int(os.getenv("OB_SWING_WINDOW", "5"))
    # Look-ahead для проверки BOS после OB
    ob_bos_lookahead: int = int(os.getenv("OB_BOS_LOOKAHEAD", "20"))
    # Максимальный look-ahead для проверки ретеста OB
    ob_retest_max_lookahead: int = int(os.getenv("OB_RETEST_MAX_LOOKAHEAD", "30"))

    # ─── FVG ─────────────────────────────────────────────────────────────
    # Минимальный % размер FVG
    fvg_min_size_pct: float = float(os.getenv("FVG_MIN_SIZE_PCT", "0.4"))
    # Lookback для поиска FVG
    fvg_lookback: int = int(os.getenv("FVG_LOOKBACK", "100"))

    # ─── Candle Quality ──────────────────────────────────────────────────
    # Множитель ATR для displacement при оценке качества свечи
    candle_displacement_atr_mult: float = float(os.getenv("CANDLE_DISPLACEMENT_ATR_MULT", "1.5"))
    # Минимальный % тела свечи для качества
    candle_min_body_pct: float = float(os.getenv("CANDLE_MIN_BODY_PCT", "0.6"))
    # Максимальное соотношение фитиля для качества
    candle_max_wick_ratio: float = float(os.getenv("CANDLE_MAX_WICK_RATIO", "0.3"))


@dataclass
class MarketStructureConfig:
    """Параметры рыночной структуры: swing points, BOS/CHoCH, MTF."""

    # Минимальный % distance filter для уровней структуры
    distance_filter_min_pct: float = float(os.getenv("DISTANCE_FILTER_MIN_PCT", "1.2"))
    # Требуемое число совпадающих таймфреймов для MTF alignment
    mtf_required_alignment: int = int(os.getenv("MTF_REQUIRED_ALIGNMENT", "2"))
    # Таймфреймы для MTF анализа (через запятую)
    mtf_timeframes: str = os.getenv("MTF_TIMEFRAMES", "1d,4h,1h")
    # Включить ли MTF анализ
    mtf_enabled: bool = os.getenv("MTF_ENABLED", "true").lower() == "true"
    # Distance filter (blocks if too close to S/R)
    distance_filter_enabled: bool = os.getenv("DISTANCE_FILTER_ENABLED", "true").lower() == "true"
    # Расчёт уровней поддержки/сопротивления
    sr_levels_enabled: bool = os.getenv("SR_LEVELS_ENABLED", "true").lower() == "true"
    # TP path quality filter
    tp_path_enabled: bool = os.getenv("TP_PATH_ENABLED", "false").lower() == "true"
    # Lookback для swing point detection
    structure_lookback: int = int(os.getenv("STRUCTURE_LOOKBACK", "50"))
    # Окно для swing point detection
    structure_swing_window: int = int(os.getenv("STRUCTURE_SWING_WINDOW", "5"))
    # Число недавних high/low для анализа
    structure_recent_count: int = int(os.getenv("STRUCTURE_RECENT_COUNT", "5"))
    # Лимит свечей для MTF OHLCV запроса
    mtf_ohlcv_limit: int = int(os.getenv("MTF_OHLCV_LIMIT", "100"))
    # Минимальное число свечей для MTF анализа
    mtf_min_candles: int = int(os.getenv("MTF_MIN_CANDLES", "20"))


@dataclass
class RiskConfig:
    """Параметры управления рисками."""

    # ─── Volatility ──────────────────────────────────────────────────────
    # Порог низкой волатильности (% ATR от цены)
    volatility_low_threshold: float = float(os.getenv("VOLATILITY_LOW_THRESHOLD", "0.8"))
    # Порог высокой волатильности (% ATR от цены)
    volatility_high_threshold: float = float(os.getenv("VOLATILITY_HIGH_THRESHOLD", "6.0"))
    # Период ATR для расчёта волатильности
    volatility_atr_period: int = int(os.getenv("VOLATILITY_ATR_PERIOD", "14"))
    # Множитель риска для высокой волатильности
    volatility_high_multiplier: float = float(os.getenv("VOLATILITY_HIGH_MULTIPLIER", "0.5"))

    # ─── Position Sizing ─────────────────────────────────────────────────
    # Риск на сделку для strong сигнала (%)
    risk_strong_pct: float = float(os.getenv("RISK_STRONG_PCT", "1.0"))
    # Риск на сделку для moderate сигнала (%)
    risk_moderate_pct: float = float(os.getenv("RISK_MODERATE_PCT", "0.5"))
    # Разрешить торговлю weak сигналов (отключена по умолчанию — двойные системы скоринга не согласованы)
    risk_weak_trade: bool = os.getenv("RISK_WEAK_TRADE", "false").lower() == "true"
    # Размер позиции для weak сигнала (%)
    risk_weak_pct: float = float(os.getenv("RISK_WEAK_PCT", "0.25"))
    # Минимальный ATR % для торговли (иначе no-trade zone)
    no_trade_min_atr_pct: float = float(os.getenv("NO_TRADE_MIN_ATR_PCT", "0.6"))

    # ─── Correlation ─────────────────────────────────────────────────────
    # Множитель риска при misaligned корреляции BTC/ETH
    correlation_misaligned_multiplier: float = float(os.getenv("CORRELATION_MISALIGNED_MULTIPLIER", "0.5"))

    # ─── Filter toggles (scanner additional gates) ─────────────────────
    # Volatility regime filter (blocks breakout in low vol)
    volatility_filter_enabled: bool = os.getenv("VOLATILITY_FILTER_ENABLED", "true").lower() == "true"
    # No-trade zones check
    no_trade_zones_enabled: bool = os.getenv("NO_TRADE_ZONES_ENABLED", "true").lower() == "true"
    # Dynamic risk filter
    dynamic_risk_enabled: bool = os.getenv("DYNAMIC_RISK_ENABLED", "true").lower() == "true"

    # ─── Market Regime ───────────────────────────────────────────────────
    # Порог ADX для трендового режима (согласован с adx_min signal_engine)
    regime_trend_adx: float = float(os.getenv("REGIME_TREND_ADX", "25"))
    # Порог ADX для range режима (согласован с adx_min signal_engine)
    regime_range_adx: float = float(os.getenv("REGIME_RANGE_ADX", "20"))
    # Порог ATR percentile для compression режима
    regime_compression_atr_pct: float = float(os.getenv("REGIME_COMPRESSION_ATR_PCT", "20"))
    # Lookback для расчёта ATR percentile
    regime_atr_lookback: int = int(os.getenv("REGIME_ATR_LOOKBACK", "100"))
    # Окно EMA spread trend analysis
    regime_ema_spread_window: int = int(os.getenv("REGIME_EMA_SPREAD_WINDOW", "5"))
    # Порог % изменения EMA spread для rising/falling
    regime_ema_spread_change_pct: float = float(os.getenv("REGIME_EMA_SPREAD_CHANGE_PCT", "0.05"))
    # Множитель для проверки rising ATR/volume
    regime_rising_multiplier: float = float(os.getenv("REGIME_RISING_MULTIPLIER", "1.1"))
    # Окно для проверки rising ATR/volume
    regime_rising_window: int = int(os.getenv("REGIME_RISING_WINDOW", "10"))
    # Fallback confidence для неизвестного режима
    regime_fallback_confidence: float = float(os.getenv("REGIME_FALLBACK_CONFIDENCE", "0.3"))

    # ─── TP Path ─────────────────────────────────────────────────────────
    # Порог blocked для TP path analysis
    tp_path_blocked_threshold: int = int(os.getenv("TP_PATH_BLOCKED_THRESHOLD", "-20"))
    # Базовый score для clear TP path
    tp_path_clear_score: int = int(os.getenv("TP_PATH_CLEAR_SCORE", "15"))
    # Штраф за obstacle в TP path
    tp_path_obstacle_penalty: int = int(os.getenv("TP_PATH_OBSTACLE_PENALTY", "-10"))


@dataclass
class DerivativesConfig:
    """Параметры деривативов: funding, OI, BTC/ETH корреляция."""

    # Порог strong funding rate
    funding_strong_threshold: float = float(os.getenv("FUNDING_STRONG_THRESHOLD", "0.0003"))
    # Зона нейтрального funding
    funding_neutral_zone: float = float(os.getenv("FUNDING_NEUTRAL_ZONE", "0.0001"))
    # Порог moderate OI change (%)
    oi_moderate_threshold: float = float(os.getenv("OI_MODERATE_THRESHOLD", "0.5"))
    # Порог strong OI change (%)
    oi_strong_threshold: float = float(os.getenv("OI_STRONG_THRESHOLD", "2.0"))
    # Lookback для OI (часы)
    oi_lookback_hours: int = int(os.getenv("OI_LOOKBACK_HOURS", "24"))
    # Символ BTC для корреляции
    btc_symbol: str = os.getenv("BTC_SYMBOL", "BTC/USDT")
    # Таймфрейм для EMA200 BTC
    btc_ema200_timeframe: str = os.getenv("BTC_EMA200_TIMEFRAME", "4h")
    # Включить корреляцию с BTC
    btc_correlation_enabled: bool = os.getenv("BTC_CORRELATION_ENABLED", "true").lower() == "true"
    # Символ ETH для корреляции
    eth_symbol: str = os.getenv("ETH_SYMBOL", "ETH/USDT")
    # Символы для корреляции ETH (через запятую)
    eth_correlation_symbols_str: str = os.getenv("ETH_CORRELATION_SYMBOLS", "OP/USDT,ARB/USDT")
    # Включить корреляцию с ETH
    eth_correlation_enabled: bool = os.getenv("ETH_CORRELATION_ENABLED", "true").lower() == "true"

    @property
    def eth_correlation_symbols(self) -> list[str]:
        return [s.strip() for s in self.eth_correlation_symbols_str.split(",") if s.strip()]


@dataclass
class ScoringConfig:
    """Параметры скоринга и verdict."""

    # Порог confidence для STRONG verdict
    confidence_strong_threshold: float = float(os.getenv("CONFIDENCE_STRONG_THRESHOLD", "65"))
    # Порог confidence для MODERATE verdict
    confidence_moderate_threshold: float = float(os.getenv("CONFIDENCE_MODERATE_THRESHOLD", "40"))
    # Порог quality для STRONG (унифицирован с confidence)
    quality_strong_threshold: float = float(os.getenv("QUALITY_STRONG_THRESHOLD", "65"))
    # Порог quality для MODERATE (унифицирован с confidence)
    quality_moderate_threshold: float = float(os.getenv("QUALITY_MODERATE_THRESHOLD", "30"))
    # Минимальное число условий для сигнала
    min_score_for_signal: int = int(os.getenv("MIN_SCORE_FOR_SIGNAL", "2"))

    # ─── Weighted Factor Model (signal_engine) ───────────────────────────
    # TREND weights
    w_supertrend: int = int(os.getenv("W_SUPERTREND", "5"))
    w_ema: int = int(os.getenv("W_EMA", "10"))
    # MOMENTUM weights
    w_macd: int = int(os.getenv("W_MACD", "10"))
    w_rsi: int = int(os.getenv("W_RSI", "5"))
    w_volume: int = int(os.getenv("W_VOLUME", "15"))
    w_adx: int = int(os.getenv("W_ADX", "5"))
    w_dmi: int = int(os.getenv("W_DMI", "5"))
    # STRUCTURE weights
    w_bos: int = int(os.getenv("W_BOS", "15"))
    w_sweep: int = int(os.getenv("W_SWEEP", "10"))
    w_ob: int = int(os.getenv("W_OB", "10"))
    # CONTEXT weights
    w_btc: int = int(os.getenv("W_BTC", "10"))
    w_funding: int = int(os.getenv("W_FUNDING", "5"))
    w_oi: int = int(os.getenv("W_OI", "10"))

    # ─── Confidence V2 weights ───────────────────────────────────────────
    w_htf_trend: int = int(os.getenv("W_HTF_TREND", "20"))
    w_structure: int = int(os.getenv("W_STRUCTURE", "15"))
    w_liquidity: int = int(os.getenv("W_LIQUIDITY", "20"))
    w_conf_volume: int = int(os.getenv("W_CONF_VOLUME", "5"))
    w_btc_corr: int = int(os.getenv("W_BTC_CORR", "15"))
    w_conf_funding: int = int(os.getenv("W_CONF_FUNDING", "5"))
    w_conf_oi: int = int(os.getenv("W_CONF_OI", "5"))
    w_conf_rsi: int = int(os.getenv("W_CONF_RSI", "5"))
    w_conf_macd: int = int(os.getenv("W_CONF_MACD", "5"))
    w_conf_adx: int = int(os.getenv("W_CONF_ADX", "5"))

    # ─── Blending ────────────────────────────────────────────────────────
    # Доля technical score в итоговой confidence
    tech_confidence_blend: float = float(os.getenv("TECH_CONFIDENCE_BLEND", "0.6"))
    # Доля market confidence в итоговой confidence
    market_confidence_blend: float = float(os.getenv("MARKET_CONFIDENCE_BLEND", "0.4"))
    # Доля исторического WR в blended confidence
    historical_wr_blend: float = float(os.getenv("HISTORICAL_WR_BLEND", "0.4"))

    # ─── Filter toggles ──────────────────────────────────────────────────
    # Confidence V2 scoring (10-factor weighted)
    confidence_v2_enabled: bool = os.getenv("CONFIDENCE_V2_ENABLED", "true").lower() == "true"

    # Качество (strong/moderate/weak) определяется quality_* порогами в confidence_v2._quality_label().
    # По умолчанию 65/40 — унифицировано с confidence порогами.

    @property
    def max_signal_score(self) -> int:
        """Сумма всех весов weighted factor model."""
        return (
            self.w_supertrend + self.w_ema +
            self.w_macd + self.w_rsi + self.w_volume + self.w_adx + self.w_dmi +
            self.w_bos + self.w_sweep + self.w_ob +
            self.w_btc + self.w_funding + self.w_oi
        )


@dataclass
class SchedulerConfig:
    """Параметры расписания сканирования."""

    # Минуты для сканирования всех primary_tf (cron, через запятую)
    scan_minutes: str = os.getenv("SCAN_MINUTES", "2,17,32,47")


@dataclass
class RateLimitConfig:
    """Параметры rate limiting для Telegram-команд."""

    # Максимальное число запросов за период
    max_rate: int = int(os.getenv("RATE_LIMIT_MAX_RATE", "5"))
    # Период rate limiting (секунды)
    time_period: int = int(os.getenv("RATE_LIMIT_TIME_PERIOD", "10"))


@dataclass
class NotifierConfig:
    """Параметры форматирования уведомлений."""

    # Порог extreme Fear & Greed Index
    fng_extreme_threshold_low: int = int(os.getenv("FNG_EXTREME_LOW", "20"))
    # Порог extreme Fear & Greed Index
    fng_extreme_threshold_high: int = int(os.getenv("FNG_EXTREME_HIGH", "80"))
    # Порог long/short ratio
    long_short_ratio_threshold: float = float(os.getenv("LONG_SHORT_RATIO_THRESHOLD", "0.7"))
    # Порог позитивного sentiment
    sentiment_positive_threshold: float = float(os.getenv("SENTIMENT_POSITIVE_THRESHOLD", "0.2"))
    # Порог негативного sentiment
    sentiment_negative_threshold: float = float(os.getenv("SENTIMENT_NEGATIVE_THRESHOLD", "-0.2"))
    # Число попыток отправки сообщения
    send_retries: int = int(os.getenv("SEND_RETRIES", "3"))


@dataclass
class SupportResistanceConfig:
    """Параметры уровней поддержки/сопротивления."""

    # Окно для swing level detection
    sr_window: int = int(os.getenv("SR_WINDOW", "10"))
    # Максимальное число уровней поддержки/сопротивления
    sr_max_levels: int = int(os.getenv("SR_MAX_LEVELS", "5"))
    # Порог кластеризации (0.5%)
    sr_cluster_threshold: float = float(os.getenv("SR_CLUSTER_THRESHOLD", "0.005"))
    # Минимальный % distance от entry для close support/resistance
    sr_min_distance_pct: float = float(os.getenv("SR_MIN_DISTANCE_PCT", "1.0"))
    # Лимит запроса для S/R уровней
    sr_ohlcv_limit: int = int(os.getenv("SR_OHLCV_LIMIT", "100"))


@dataclass
class WebConfig:
    """Параметры веб-сервера (дашборд)."""

    # Порт веб-сервера
    port: int = int(os.getenv("WEB_PORT", "3001"))
    # Хост веб-сервера
    host: str = os.getenv("WEB_HOST", "0.0.0.0")
    # Включить веб-сервер
    enabled: bool = os.getenv("WEB_ENABLED", "true").lower() == "true"
    # Интервал обновлений (секунды)
    update_interval: int = int(os.getenv("WEB_UPDATE_INTERVAL", "5"))


@dataclass
class AppConfig:
    """Главная конфигурация приложения."""

    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    market_structure: MarketStructureConfig = field(default_factory=MarketStructureConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    derivatives: DerivativesConfig = field(default_factory=DerivativesConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    notifier: NotifierConfig = field(default_factory=NotifierConfig)
    support_resistance: SupportResistanceConfig = field(default_factory=SupportResistanceConfig)
    web: WebConfig = field(default_factory=WebConfig)

    # URL базы данных
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/signals.db")
    # Уровень логирования
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    # Файл логирования
    log_file: str = os.getenv("LOG_FILE", "logs/bot.log")

    # Cooldown между сигналами по одному инструменту (минуты)
    signal_cooldown_minutes: int = int(os.getenv("SIGNAL_COOLDOWN_MINUTES", "45"))

    # Контекстный модуль
    context_enabled: bool = os.getenv("CONTEXT_ENABLED", "true").lower() == "true"
    context_min_verdict: str = os.getenv("CONTEXT_MIN_VERDICT", "WEAK")
    context_block_on_blocked: bool = os.getenv("CONTEXT_BLOCK_ON_BLOCKED", "true").lower() == "true"

    # Уведомления о заблокированных сигналах
    signal_block_notify: bool = os.getenv("SIGNAL_BLOCK_NOTIFY", "true").lower() == "true"
    cryptopanic_api_key: str = os.getenv("CRYPTOPANIC_API_KEY", "")
    coingecko_symbol_map_str: str = os.getenv("COINGECKO_SYMBOL_MAP", "BTC/USDT:bitcoin,ETH/USDT:ethereum")

    # Timeout для context fetcher (секунды)
    context_fetch_timeout: float = float(os.getenv("CONTEXT_FETCH_TIMEOUT", "10"))

    def _parse_coingecko_map(self, map_str: str) -> dict[str, str]:
        result = {}
        for pair in map_str.split(","):
            if ":" in pair:
                symbol, slug = pair.strip().split(":")
                result[symbol.strip()] = slug.strip()
        return result

    @property
    def coingecko_symbol_map(self) -> dict[str, str]:
        return self._parse_coingecko_map(self.coingecko_symbol_map_str)

    # ─── Convenience properties для liquidity ────────────────────────────

    @property
    def liquidity_sweep_max_reclaim_candles(self) -> int:
        return self.liquidity.sweep_max_reclaim_candles

    @property
    def liquidity_sweep_min_volume_ratio(self) -> float:
        return self.liquidity.sweep_min_volume_ratio

    @property
    def liquidity_ob_min_displacement_pct(self) -> float:
        return self.liquidity.ob_min_displacement_pct

    @property
    def liquidity_ob_max_age_candles(self) -> int:
        return self.liquidity.ob_max_age_candles

    @property
    def liquidity_fvg_min_size_pct(self) -> float:
        return self.liquidity.fvg_min_size_pct

    @property
    def liquidity_fvg_lookback(self) -> int:
        return self.liquidity.fvg_lookback

    @property
    def liquidity_candle_displacement_atr_mult(self) -> float:
        return self.liquidity.candle_displacement_atr_mult

    @property
    def liquidity_candle_min_body_pct(self) -> float:
        return self.liquidity.candle_min_body_pct

    @property
    def liquidity_candle_max_wick_ratio(self) -> float:
        return self.liquidity.candle_max_wick_ratio

    @property
    def liquidity_sweep_fast_reclaim_candles(self) -> int:
        return self.liquidity.sweep_fast_reclaim_candles

    @property
    def liquidity_sweep_min_wick_body_ratio(self) -> float:
        return self.liquidity.sweep_min_wick_body_ratio

    @property
    def liquidity_ob_min_displacement_atr(self) -> float:
        return self.liquidity.ob_min_displacement_atr

    @property
    def liquidity_ob_min_volume_ratio(self) -> float:
        return self.liquidity.ob_min_volume_ratio

    @property
    def liquidity_ob_retest_required(self) -> bool:
        return self.liquidity.ob_retest_required


# Mapping: DB key → (config_attribute_path, type)
FILTER_TOGGLE_KEYS: dict[str, tuple[str, type]] = {
    "adx_filter": ("trading.adx_filter_enabled", bool),
    "ema_alignment": ("trading.ema_alignment_enabled", bool),
    "ema_spread": ("trading.ema_spread_enabled", bool),
    "trigger": ("trading.trigger_required", bool),
    "candle_close": ("trading.candle_close_enabled", bool),
    "min_score": ("trading.min_score_enabled", bool),
    "compression": ("trading.compression_enabled", bool),
    "confirm_tf": ("trading.confirm_tf_enabled", bool),
    "ema_slope": ("trading.ema_slope_check", bool),
    "macd_slope": ("trading.macd_slope_check", bool),
    "mtf": ("market_structure.mtf_enabled", bool),
    "distance_filter": ("market_structure.distance_filter_enabled", bool),
    "sr_levels": ("market_structure.sr_levels_enabled", bool),
    "tp_path": ("market_structure.tp_path_enabled", bool),
    "btc_corr": ("derivatives.btc_correlation_enabled", bool),
    "eth_corr": ("derivatives.eth_correlation_enabled", bool),
    "volatility": ("risk.volatility_filter_enabled", bool),
    "no_trade_zones": ("risk.no_trade_zones_enabled", bool),
    "dynamic_risk": ("risk.dynamic_risk_enabled", bool),
    "context": ("context_enabled", bool),
    "confidence_v2": ("scoring.confidence_v2_enabled", bool),
    "signal_block": ("signal_block_notify", bool),
}

FILTER_PARAM_KEYS: dict[str, tuple[str, type]] = {
    "adx_min": ("trading.adx_min", float),
    "ema_fast": ("trading.ema_fast", int),
    "ema_slow": ("trading.ema_slow", int),
    "ema_trend": ("trading.ema_trend", int),
    "min_ema_spread_pct": ("trading.min_ema_spread_pct", float),
    "rsi_period": ("trading.rsi_period", int),
    "rsi_overbought": ("trading.rsi_overbought", float),
    "rsi_oversold": ("trading.rsi_oversold", float),
    "macd_fast": ("trading.macd_fast", int),
    "macd_slow": ("trading.macd_slow", int),
    "macd_signal": ("trading.macd_signal", int),
    "adx_period": ("trading.adx_period", int),
    "atr_period": ("trading.atr_period", int),
    "atr_multiplier_sl": ("trading.atr_multiplier_sl", float),
    "atr_multiplier_tp": ("trading.atr_multiplier_tp", float),
    "supertrend_period": ("trading.supertrend_period", int),
    "supertrend_multiplier": ("trading.supertrend_multiplier", float),
    "volume_factor": ("trading.volume_factor", float),
    "volume_sma_period": ("trading.volume_sma_period", int),
    "min_score_for_signal": ("scoring.min_score_for_signal", int),
    "confirm_timeframe": ("trading.confirm_timeframe", str),
    "signal_cooldown_minutes": ("signal_cooldown_minutes", int),
    # MarketStructure params
    "distance_filter_min_pct": ("market_structure.distance_filter_min_pct", float),
    "mtf_required_alignment": ("market_structure.mtf_required_alignment", int),
    "structure_lookback": ("market_structure.structure_lookback", int),
    "structure_swing_window": ("market_structure.structure_swing_window", int),
    # Derivatives params
    "funding_strong_threshold": ("derivatives.funding_strong_threshold", float),
    "oi_moderate_threshold": ("derivatives.oi_moderate_threshold", float),
    "oi_strong_threshold": ("derivatives.oi_strong_threshold", float),
    # Risk params
    "volatility_low_threshold": ("risk.volatility_low_threshold", float),
    "volatility_high_threshold": ("risk.volatility_high_threshold", float),
    "no_trade_min_atr_pct": ("risk.no_trade_min_atr_pct", float),
    "risk_strong_pct": ("risk.risk_strong_pct", float),
    "risk_moderate_pct": ("risk.risk_moderate_pct", float),
    # Context params
    "context_min_verdict": ("context_min_verdict", str),
    "context_fetch_timeout": ("context_fetch_timeout", float),
    # Scoring params
    "confidence_strong_threshold": ("scoring.confidence_strong_threshold", float),
    "confidence_moderate_threshold": ("scoring.confidence_moderate_threshold", float),
    "quality_strong_threshold": ("scoring.quality_strong_threshold", float),
    "quality_moderate_threshold": ("scoring.quality_moderate_threshold", float),
}

# ─── Singleton ────────────────────────────────────────────────────────────
config = AppConfig()


async def reload_config() -> None:
    """Горячая перезагрузка конфигурации.

    Перечитывает .env и пересоздаёт глобальный singleton `config`.
    Все модули, импортирующие `config.settings.config`, получат новые значения
    при следующем обращении (синглтон заменяется in-place).
    """
    global config
    load_dotenv()
    config = AppConfig()
    from storage.database import db
    if hasattr(db, '_session_factory') and db._session_factory is not None:
        await reload_filter_toggles()


def _set_nested_config(obj, path: str, value):
    """Set a value on a nested config object using dot-separated path."""
    parts = path.split(".")
    current = obj
    for part in parts[:-1]:
        current = getattr(current, part)
    setattr(current, parts[-1], value)


def _get_nested_config(obj, path: str):
    """Get a value from a nested config object using dot-separated path."""
    parts = path.split(".")
    current = obj
    for part in parts:
        current = getattr(current, part)
    return current


async def reload_filter_toggles() -> None:
    """Load filter toggle / param overrides from DB into the global config singleton.

    Reads keys:
      - `filter:toggle:<key>` — boolean toggles
      - `filter:param:<key>` — typed parameter values
      - `param:<UPPER_NAME>` — legacy /setparam format (backward compat)
    """
    from storage.database import db
    for key, (attr_path, _) in FILTER_TOGGLE_KEYS.items():
        db_val = await db.get_setting(f"filter:toggle:{key}", "")
        if db_val != "":
            _set_nested_config(config, attr_path, db_val.lower() == "true")
    for key, (attr_path, cast_type) in FILTER_PARAM_KEYS.items():
        db_val = await db.get_setting(f"filter:param:{key}", "")
        if db_val != "":
            try:
                _set_nested_config(config, attr_path, cast_type(db_val))
            except (ValueError, TypeError):
                pass
        else:
            # Legacy /setparam format: param:EMA_FAST
            legacy_key = f"param:{key.upper()}"
            legacy_val = await db.get_setting(legacy_key, "")
            if legacy_val != "":
                try:
                    _set_nested_config(config, attr_path, cast_type(legacy_val))
                except (ValueError, TypeError):
                    pass


async def refresh_runtime_symbols() -> None:
    """Перечитать список символов из БД. Зови при старте и после /addsymbol / /removesymbol.

    dynamic_symbols из БД — это ДОБАВЛЕННЫЕ символы (через /addsymbol).
    Итоговый список = env SYMBOLS + dynamic.
    """
    global _runtime_symbols_cache
    from storage.database import db  # lazy чтобы избежать циклов импорта
    dynamic = await db.get_dynamic_symbols()
    if dynamic:
        merged = list(config.trading.symbols)
        for s in dynamic:
            if s not in merged:
                merged.append(s)
        _runtime_symbols_cache = merged
    else:
        _runtime_symbols_cache = config.trading.symbols


# Runtime symbols cache — динамически обновляется через /addsymbol / /removesymbol
_runtime_symbols_cache: Optional[list[str]] = None


def get_active_symbols() -> list[str]:
    return _runtime_symbols_cache if _runtime_symbols_cache is not None else config.trading.symbols
