"""
send_strk_report.py — Send comprehensive STRK fundamental analysis to Telegram (multi-part).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import config
from bot.notifier import get_bot
from telegram.constants import ParseMode
from loguru import logger


PART1 = """📊 <b>ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ: STRK (StarkNet)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>📌 Текущие метрики</b>
├ Цена: $0.034
├ ATH: $4.41 (−99.3% от пика)
├ Market Cap: ~$215M
├ FDV: ~$338M
├ Circulating: 6.58B / 10B (65.8%)
├ Застейкано: 1.3B+ STRK (22% от circulating)
├ TVL (Starknet): ~$415M
└ Объём 24ч: ~$22M

<b>🔧 Токеномика и разблокировки</b>
├ Ежемесячный unlock: ~127M STRK (~3% от MCAP)
├ Следующий unlock: 20 июля 2026 (175M STRK)
├ Осталось unlocks: 56 событий до февраля 2031
├ Оставшийся объём: 3.22B STRK (32.2% от supply)
└ Эпоха inflation заканчивается: март 2027

⚠️ <b>Ключевой риск:</b> предсказуемое давление продаж каждые 15-20 числа. Исторически цена падала на 5-9% в районе unlock. Однако 22% застейканного supply частично нивелирует этот эффект."""

PART2 = """🏗 <b>Технология: ZK-STARK vs POS vs POW</b>

<b>Что такое StarkNet?</b>
L2 над Ethereum —Validity Rollup на ZK-STARK proofs. Каждая пачка транзакций сопровождается криптографическим доказательством корректности, проверяемым на Ethereum.

┌─────────────┬──────────────┬──────────────┬──────────────┐
│             │ <b>POW</b> (BTC)   │ <b>POS</b> (ETH)   │ <b>ZK-Rollup</b>  │
├─────────────┼──────────────┼──────────────┼──────────────┤
│ Безопасность│ Энергия      │ Стейкинг    │ Математика   │
│ Скорость    │ 7 TPS        │ 15-30 TPS   │ 100-400 TPS  │
│ Gas         │ $1-50        │ $0.5-5      │ $0.01-0.05   │
│ Квантовое   │ Уязвим       │ Уязвим      │ <b>Устойчиво</b> │
└─────────────┴──────────────┴──────────────┴──────────────┘

<b>Почему ZK — это прорыв?</b>
1. <b>Post-quantum安全:</b> STARK proofs устойчивы к квантовым атакам. BTC и ETH — нет. StarkNet готов к пост-квантовой эре ЗАРАНЕЕ (дедлайн Google: 2029)
2. <b>Масштабируемость:</b> Вычисления off-chain, проверка on-chain. Тысячи TPS при $0.01 за транзакцию
3. <b>Без trusted setup:</b> STARKs полностью прозрачны (в отличие от SNARKs)
4. <b>Account abstraction:</b> Умные кошельки из коробки — мультиподписи, рековери, соцсети как ключи"""

PART3 = """<b>Может ли ZK "взорвать" рынок?</b>
Да, но не в 2026. Текущая реальность:
├ Optimistic Rollups = 80% TVL L2 ($40B+)
├ ZK Rollups = 20% TVL L2 (~$10B)
├ Starknet TVL: $415M vs Arbitrum: $16.9B (в 40 раз меньше)
└ Но ZK растёт БЫСТРЕЕ по DAU и developer activity

ZK — следующий цикл инфраструктуры. Когда provers подешевеют, ZK rollups станут default для институциональных проектов (приватность, compliance, быстрая финализация).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>🎯 Катализаторы 2026-2027</b>
├ ✅ v0.14.3 (22 июня): динамические gas fees в STRK
├ ✅ STRK20 + strkBTC: приватные транзакции + BTC DeFi
├ ✅ Staking v3: делегация + голосование
├ ✅ #1 по developer activity среди Ethereum L2
├ ✅ 300M+ транзакций на mainnet
├ ⚠️ Окончание unlocks: март 2027
└ ⚠️ StarkWare сократил команду → фокус на продуктах"""

PART4 = """📈 <b>ПРОГНОЗЫ РОСТА</b>

<b>🔴 Пессимистичный сценарий</b>
Цель 2026: $0.025 — $0.040
Цель 2027: $0.06 — $0.10
Цель 2030: $0.15 — $0.30

Сценарий: Unlocks давят, экосистема не растёт, ZK rollups проигрывают. Cairo сложен для разработчиков. Риск: −25% до $0.025.

<b>🟡 Средний (наиболее вероятный)</b>
Цель 2026: $0.08 — $0.15
Цель 2027: $0.18 — $0.35
Цель 2030: $0.50 — $1.00

Сценарий: Unlocks заканчиваются марте 2027. STRK20 и BTCFi привлекают. ZK выигрывают 30-35% L2 рынка к 2028. StarkNet — ниша приватного DeFi и институциональных settlement. Рост ×3-10 к 2028.

<b>🟢 Оптимистичный сценарий</b>
Цель 2026: $0.20 — $0.30
Цель 2027: $0.50 — $1.50
Цель 2030: $2.00 — $5.00+

Сценарий: ZK becomes default L2. StarkNet = основной settlement для BTC DeFi. Post-quantum narrative усиливается. Халвинг 2028 даёт ×10-15 от дна."""

PART5 = """💰 <b>СТОИТ ЛИ НАБИРАТЬ НА СПОТ?</b>

<b>Аргументы ЗА:</b>
├ ✅ Цена на историческом минимуме (−99.3% от ATH)
├ ✅ 22% застейкано → long-term holders доминируют
├ ✅ STARK = пост-квантовая устойчивость
├ ✅ Developer activity #1 среди Ethereum L2
├ ✅ Unlocks заканчиваются в марте 2027
├ ✅ FDV $338M — дёшево для L2 с реальной технологией
└ ✅ ZK narrative будет усиливаться

<b>Аргументы ПРОТИВ:</b>
├ ❌ Ежемесячные unlocks = давление продаж
├ ❌ TVL $415M vs конкуренты $1B-17B
├ ❌ Cairo не EVM → сложность для разработчиков
├ ❌ Sequencer централизован (Stage 1)
├ ❌ Команта StarkWare сокращается
├ ❌ Конкуренция: zkSync, Scroll, Linea
└ ❌ Рынок в Extreme Fear (12)

<b>📝 Стратегия:</b>
1. <b>DCA</b> — лучшая стратегия
2. <b>Закупка после unlock</b> (20 июля) — исторически лучшие точки входа
3. <b>Размер:</b> не более 2-3% от портфеля
4. <b>Горизонт:</b> 12-24 месяца
5. <b>Не ловить нож:</b> ниже $0.025 — дождаться стабилизации

<b>Вердикт:</b> STRK — <b>высокорисковая ставка на ZK-будущее</b>. Технология сильная, экосистема отстаёт. Пригодится тем, кто верит в ZK и готов ждать 1-2 цикла.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<i>⚠️ Не является финансовой рекомендацией. DYOR.</i>
<i>📅 6 июля 2026 | CoinGecko, L2BEAT, Starknet Docs</i>"""


async def run():
    bot = get_bot()
    channel_id = config.telegram.channel_id

    if not channel_id:
        logger.error("TELEGRAM_CHANNEL_ID not set!")
        for p in [PART1, PART2, PART3, PART4, PART5]:
            print(p)
            print("\n\n")
        return

    for i, part in enumerate([PART1, PART2, PART3, PART4, PART5], 1):
        logger.info(f"Sending part {i}/5 to {channel_id}...")
        try:
            await bot.send_message(
                chat_id=channel_id,
                text=part,
                parse_mode=ParseMode.HTML,
            )
            logger.info(f"Part {i} sent!")
            await asyncio.sleep(1)  # rate limit
        except Exception as e:
            logger.error(f"Part {i} failed: {e}")
            try:
                safe = part.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
                await bot.send_message(chat_id=channel_id, text=safe)
                logger.info(f"Part {i} sent without HTML")
                await asyncio.sleep(1)
            except Exception as e2:
                logger.error(f"Part {i} retry also failed: {e2}")

    logger.info("All parts sent!")


if __name__ == "__main__":
    asyncio.run(run())
