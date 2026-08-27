"""
pnl_monitor.py — Фоновая задача для мониторинга и обновления PnL по сигналам
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger
from config.settings import config
from data.exchange_client import exchange_client
from storage.database import db


class PnLMonitor:
    """Монитор для отслеживания исполнения сигналов (hit SL/TP) и обновления их статуса."""

    def __init__(self, check_interval_seconds: int = 30):
        self._check_interval = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Запускает фоновую задачу мониторинга."""
        if self._running:
            logger.warning("PnL monitor is already running")
            return
            
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"PnL monitor started with {self._check_interval}s interval")

    async def stop(self):
        """Останавливает фоновую задачу мониторинга."""
        if not self._running:
            return
            
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PnL monitor stopped")

    async def _monitor_loop(self):
        """Основной цикл мониторинга."""
        while self._running:
            try:
                await self._check_open_signals()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in PnL monitor loop: {e}", exc_info=True)
                await asyncio.sleep(self._check_interval)  # Continue despite errors

    async def _check_open_signals(self):
        """Проверяет все открытые сигналы и обновляет их статус при достижении SL/TP."""
        # Получаем все сигналы со статусом PENDING
        # Для простоты в этой версии мы будем получать недавние сигналы и фильтровать в памяти
        # В продакшене лучше добавить метод в БД для получения только PENDING сигналов
        
        recent_signals = await db.get_recent_signals(limit=100)  # Проверяем последние 100 сигналов
        open_signals = [s for s in recent_signals if s.status == "PENDING"]
        
        if not open_signals:
            return
            
        logger.debug(f"Checking {len(open_signals)} open signals for SL/TP")
        
        for signal in open_signals:
            try:
                await self._check_signal(signal)
            except Exception as e:
                logger.error(f"Error checking signal {signal.id}: {e}", exc_info=True)

    async def _check_signal(self, signal):
        """Проверяет один сигнал на достижение SL/TP."""
        # Получаем текущую цену
        df = await exchange_client.fetch_ohlcv(signal.symbol, signal.timeframe, limit=1)
        if df is None or len(df) == 0:
            return
            
        current_price = df.iloc[0]["close"]
        
        # Проверяем достижение SL или TP
        hit_sl = False
        hit_tp = False
        pnl_percent = None
        
        if signal.signal_type == "BUY":
            # Для лонга: SL ниже входа, TP выше входа
            if signal.sl and current_price <= signal.sl:
                hit_sl = True
                # PnL = (exit - entry) / entry * 100%
                pnl_percent = ((current_price - signal.close_price) / signal.close_price) * 100
            elif signal.tp and current_price >= signal.tp:
                hit_tp = True
                pnl_percent = ((current_price - signal.close_price) / signal.close_price) * 100
                
        elif signal.signal_type == "SELL":
            # Для шорта: SL выше входа, TP ниже входа
            if signal.sl and current_price >= signal.sl:
                hit_sl = True
                # PnL = (entry - exit) / entry * 100%
                pnl_percent = ((signal.close_price - current_price) / signal.close_price) * 100
            elif signal.tp and current_price <= signal.tp:
                hit_tp = True
                pnl_percent = ((signal.close_price - current_price) / signal.close_price) * 100
        
        # Если достигнут SL или TP, обновляем сигнал
        if hit_sl or hit_tp:
            status = "LOSS" if hit_sl else "WIN"
            closed_at = datetime.now(timezone.utc)
            
            await db.update_signal_pnl(
                signal_id=signal.id,
                status=status,
                pnl_percent=pnl_percent,
                closed_at=closed_at
            )
            
            logger.info(
                f"Signal {signal.id} ({signal.signal_type} {signal.symbol}) closed: "
                f"{status} with {pnl_percent:.2f}% PnL "
                f"(price: {current_price:.4f}, SL: {signal.sl}, TP: {signal.tp})"
            )


# Singleton instance
pnl_monitor = PnLMonitor()