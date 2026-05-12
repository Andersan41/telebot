"""
indicators/engine.py — Расчёт технических индикаторов
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import pandas_ta as ta
import numpy as np
from loguru import logger
from config.settings import config


@dataclass
class IndicatorValues:
    """Результат расчёта индикаторов на последней свече"""
    symbol: str
    timeframe: str

    # Цены
    close: float
    high: float
    low: float
    volume: float

    # EMA
    ema_fast: float
    ema_slow: float
    ema_trend: float
    ema_fast_prev: float    # EMA fast на предыдущей свече
    ema_slow_prev: float    # EMA slow на предыдущей свече

    # RSI
    rsi: float

    # MACD
    macd: float
    macd_signal: float
    macd_hist: float
    macd_hist_prev: float

    # ADX
    adx: float
    dmi_plus: float
    dmi_minus: float

    # ATR
    atr: float

    # Supertrend
    supertrend: float
    supertrend_direction: int  # 1 = up (bullish), -1 = down (bearish)

    # Volume
    volume_sma: float

    # Вычисляемые свойства
    @property
    def ema_bullish_cross(self) -> bool:
        """EMA fast пересекла EMA slow снизу вверх"""
        return self.ema_fast_prev <= self.ema_slow_prev and self.ema_fast > self.ema_slow

    @property
    def ema_bearish_cross(self) -> bool:
        """EMA fast пересекла EMA slow сверху вниз"""
        return self.ema_fast_prev >= self.ema_slow_prev and self.ema_fast < self.ema_slow

    @property
    def ema_bullish_alignment(self) -> bool:
        """EMA fast > EMA slow > EMA trend"""
        return self.ema_fast > self.ema_slow > self.ema_trend

    @property
    def ema_bearish_alignment(self) -> bool:
        """EMA fast < EMA slow < EMA trend"""
        return self.ema_fast < self.ema_slow < self.ema_trend

    @property
    def macd_bullish_cross(self) -> bool:
        """MACD гистограмма переходит от отрицательной к положительной"""
        return self.macd_hist_prev < 0 and self.macd_hist > 0

    @property
    def macd_bearish_cross(self) -> bool:
        """MACD гистограмма переходит от положительной к отрицательной"""
        return self.macd_hist_prev > 0 and self.macd_hist < 0

    @property
    def volume_above_avg(self) -> bool:
        return self.volume > self.volume_sma * config.trading.volume_factor

    @property
    def trend_is_strong(self) -> bool:
        return self.adx >= config.trading.adx_min

    @property
    def supertrend_bullish(self) -> bool:
        return self.supertrend_direction == 1

    @property
    def supertrend_bearish(self) -> bool:
        return self.supertrend_direction == -1


class IndicatorEngine:
    def calculate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[IndicatorValues]:
        """
        Считаем все индикаторы на переданном DataFrame.
        Возвращает IndicatorValues для последней (закрытой) свечи.
        """
        try:
            if len(df) < config.trading.candles_limit // 2:
                logger.warning(f"Not enough candles for {symbol} {timeframe}: {len(df)}")
                return None

            cfg = config.trading

            # EMA
            df["ema_fast"] = ta.ema(df["close"], length=cfg.ema_fast)
            df["ema_slow"] = ta.ema(df["close"], length=cfg.ema_slow)
            df["ema_trend"] = ta.ema(df["close"], length=cfg.ema_trend)

            # RSI
            df["rsi"] = ta.rsi(df["close"], length=cfg.rsi_period)

            # MACD
            macd_df = ta.macd(df["close"], fast=cfg.macd_fast, slow=cfg.macd_slow, signal=cfg.macd_signal)
            if macd_df is not None:
                df["macd"] = macd_df.iloc[:, 0]
                df["macd_signal"] = macd_df.iloc[:, 2]
                df["macd_hist"] = macd_df.iloc[:, 1]
            else:
                df["macd"] = np.nan
                df["macd_signal"] = np.nan
                df["macd_hist"] = np.nan

            # ADX + DMI
            adx_df = ta.adx(df["high"], df["low"], df["close"], length=cfg.adx_period)
            if adx_df is not None:
                adx_cols = list(adx_df.columns)
                adx_col = [c for c in adx_cols if c.startswith("ADX_") and "R" not in c]
                dmp_col = [c for c in adx_cols if c.startswith("DMP_")]
                dmn_col = [c for c in adx_cols if c.startswith("DMN_")]
                df["adx"] = adx_df[adx_col[0]] if adx_col else np.nan
                df["dmi_plus"] = adx_df[dmp_col[0]] if dmp_col else np.nan
                df["dmi_minus"] = adx_df[dmn_col[0]] if dmn_col else np.nan
            else:
                df["adx"] = np.nan
                df["dmi_plus"] = np.nan
                df["dmi_minus"] = np.nan

            # ATR
            df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=cfg.atr_period)

            # Volume SMA
            df["volume_sma"] = ta.sma(df["volume"], length=20)

            # Supertrend
            st_df = ta.supertrend(
                df["high"], df["low"], df["close"],
                length=cfg.supertrend_period,
                multiplier=cfg.supertrend_multiplier,
            )
            if st_df is not None:
                # pandas_ta возвращает несколько колонок; нужна SUPERT_... и SUPERTd_...
                st_cols = [c for c in st_df.columns]
                st_val_col = [c for c in st_cols if c.startswith("SUPERT_") and "d" not in c and "l" not in c and "s" not in c]
                st_dir_col = [c for c in st_cols if "SUPERTd_" in c]
                if st_val_col and st_dir_col:
                    df["supertrend"] = st_df[st_val_col[0]]
                    df["supertrend_dir"] = st_df[st_dir_col[0]]
                else:
                    df["supertrend"] = np.nan
                    df["supertrend_dir"] = 0
            else:
                df["supertrend"] = np.nan
                df["supertrend_dir"] = 0

            # Удаляем строки с NaN
            df_clean = df.dropna(subset=["ema_fast", "ema_slow", "rsi", "adx", "atr"])
            if len(df_clean) < 2:
                logger.warning(f"Not enough clean data for {symbol} {timeframe}")
                return None

            last = df_clean.iloc[-1]
            prev = df_clean.iloc[-2]

            return IndicatorValues(
                symbol=symbol,
                timeframe=timeframe,
                close=float(last["close"]),
                high=float(last["high"]),
                low=float(last["low"]),
                volume=float(last["volume"]),
                ema_fast=float(last["ema_fast"]),
                ema_slow=float(last["ema_slow"]),
                ema_trend=float(last["ema_trend"]),
                ema_fast_prev=float(prev["ema_fast"]),
                ema_slow_prev=float(prev["ema_slow"]),
                rsi=float(last["rsi"]),
                macd=float(last.get("macd", 0) or 0),
                macd_signal=float(last.get("macd_signal", 0) or 0),
                macd_hist=float(last.get("macd_hist", 0) or 0),
                macd_hist_prev=float(prev.get("macd_hist", 0) or 0),
                adx=float(last["adx"]),
                dmi_plus=float(last.get("dmi_plus", 0) or 0),
                dmi_minus=float(last.get("dmi_minus", 0) or 0),
                atr=float(last["atr"]),
                supertrend=float(last.get("supertrend", last["close"]) or last["close"]),
                supertrend_direction=int(last.get("supertrend_dir", 0) or 0),
                volume_sma=float(last.get("volume_sma", last["volume"]) or last["volume"]),
            )

        except Exception as e:
            logger.error(f"Indicator calculation error for {symbol} {timeframe}: {e}", exc_info=True)
            return None


indicator_engine = IndicatorEngine()
