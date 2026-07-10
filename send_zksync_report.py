"""
send_zksync_report.py — Send zkSync fundamental analysis to Telegram.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import config
from bot.notifier import get_bot
from telegram.constants import ParseMode
from loguru import logger


ZK_1 = """📊 <b>ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ: ZK (zkSync)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>📌 Текущие метрики</b>
├ Цена: ~$0.014
├ ATH: $0.321 (июнь 2024, −95.6%)
├ Market Cap: ~$105M
├ FDV: ~$339M
├ Circulating: 9.6B / 21B (45.7%)
├ TVL (DeFi): ~$36.4M
├ Total Value Secured: ~$325M
├ RWA on chain: $2.3B (2-й в мире!)
└ Команда: Matter Labs (Берлин, 2018)

<b>🔧 Токеномика</b>
├ Total supply: 21B ZK
├ Ecosystem Initiatives: 19.9%
├ Airdrop: 17.5%
├ Investors: 17.19%
├ Team: 16.14%
├ Token Assembly (DAO): 29.27%
├ Unlock: июнь 2024 → июнь 2028 (4 года)
├ Cliff: 1 год (июнь 2025)
└ Monthly unlock: ~408M ZK (~4.25% от float)

⚠️ <b>КРИТИЧЕСКИЙ РИСК:</b> 408M ZK ежемесячно = ~$5.7M продаж. FDV $339M vs MCAP $105M = dilution overhead ×3.2. Каждый месяц ~4.25% нового supplypressure."""

ZK_2 = """🏗 <b>Технология: ZK-Rollup + Elastic Network</b>

<b>Что такое zkSync?</b>
Ethereum L2 ZK-Rollup от Matter Labs. Состоит из:
├ <b>zkSync Era</b> — главный хаб (DeFi, NFT, RWA)
├ <b>zkSync Lite</b> — простые переводы
├ <b>ZK Stack</b> — фреймворк для создания собственных ZK-цепочек
└ <b>Elastic Network</b> — 18+ связанных ZK-цепочек

<b>Ключевые особенности:</b>
├ Полная EVM-совместимость (Solidity, Vyper)
├ SNARK proofs (в отличие от STARK у StarkNet)
├ Native account abstraction + paymaster
├ Stage 0 (не Stage 1 как StarkNet!)
├ Быстрые выводы: часы вместо 7 дней (Optimistic)
└ 10 ZK за cross-chain вызов (V31 upgrade)

<b>V31 Upgrade — Burn Flywheel:</b>
├ Каждый cross-chain вызов сжигает ZK токены
├ Дефляционный механизм привязан к usage
├ Прогноз сжигания:
│  ├ Консервативный: 18.25M ZK/год
│  ├ Базовый: 182.5M ZK/год
│  ├ Оптимистичный: 730M ZK/год
│  └ Институциональный: 3.65B ZK/год
└ При 730M сжигания = 3.5% от supply annually

<b>Elastic Network:</b>
18+ ZK-цепочек, работающих через ZK Stack. Каждая цепочка — отдельный проект со своей ликвидностью. V31 делает ихinteroperable: активы и контракты перетекают между цепочками."""

ZK_3 = """🎯 <b>Катализаторы и риски</b>

<b>✅ Катализаторы ЗА:</b>
├ Deutsche Bank на zkSync (Memento ZK Chain, $1.3T AUM)
├ Prividium = институциональная приватность
├ V31 burn mechanism = дефляция при usage
├ $2.3B RWA на zkSync (2-е место в мире!)
├ Elastic Network = масштабируемость через ZK Stack
├ Matter Labs: полный pivot на институты
├ ZK proofs = post-quantum (через апгрейд)
└ Низкий MCAP $105M при $2.3B RWA

<b>❌ Риски ПРОТИВ:</b>
├ −95.6% от ATH = damagedpsychology
├ TVL DeFi: $36.4M (катастрофически мало!)
├ Monthly unlock: 408M ZK = $5.7M/мес
├ FDV/MCAP = ×3.2 (огромный dilution overhead)
├ Matter Labs сократил команду
├ Pivot на Prividium = забыл про DeFi экосистему
├ Stage 0 (не decentralization!)
├ Deutsche Bank НЕ платит ZK fees (settles on ETH gas!)
├ Конкуренция: Arbitrum $16.9B, Base $12.8B, StarkNet $415M
└ SNARK: requires trusted setup (в отличие от STARK)"""

ZK_4 = """📈 <b>ПРОГНОЗЫ РОСТА ZK</b>

<b>🔴 Пессимистичный</b>
Цель 2026: $0.008 — $0.012
Цель 2027: $0.005 — $0.010
Цель 2030: $0.003 — $0.008

Сценарий: Unlocks давят, Prividium не приносит revenue, DeFi экосистема мертва. ZK becomes another zombie chain.

<b>🟡 Средний (наиболее вероятный)</b>
Цель 2026: $0.02 — $0.05
Цель 2027: $0.03 — $0.08
Цель 2030: $0.05 — $0.15

Сценарий: Prividium привлекает 2-3 банка, V31 burn запускается, RWA сектор растёт. Но monthly unlock давит. Рост ×2-10 от текущей.

<b>🟢 Оптимистичный</b>
Цель 2026: $0.08 — $0.15
Цель 2027: $0.15 — $0.30
Цель 2030: $0.50 — $1.00+

Сценарий: Prividium becomes institutional standard, Deutsche Bank + другие банки, burn flywheel активен, ZKnomics работает. MCAP $1-3B.

<b>💰 СТОИТ ЛИ НАБИРАТЬ?</b>

<b>Самый сложный кейс из всех L2:</b>

├ ✅ Deutsche Bank = институциональная валидация
├ ✅ $2.3B RWA = реальная utility
├ ✅ V31 burn = дефляционный механизм
├ ✅ $105M MCAP = дёшево если Prividium сработает
├ ❌ −95.6% от ATH
├ ❌ TVL DeFi $36.4M (почти 0)
├ ❌ Monthly unlock 4.25% от float
├ ❌ Matter Labs забыл про DeFi
├ ❌ Deutsche Bank НЕ использует ZK token!
└ ❌ Stage 0 = централизовано

<b>Вердикт:</b> ZK — <b>speculative bet на Prividium</b>. Если институты начнут платить ZK fees → ×10-50. Если нет → медленное умирание. Не подходит для долгосрочных позиций без пониманияPrividium-драйверов.

<b>Стратегия:</b>
├ Маленькая позиция (1-2% портфеля)
├ Только если понимаете Prividium thesis
├ DCA в зоне $0.010-0.015
├ Стоп-лосс: $0.006
├ Горизонт: 12-18 месяцев
└ Следить за: protocol fees, burn rate, new banks

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<i>⚠️ Не является финансовой рекомендацией. DYOR.</i>
<i>📅 6 июля 2026 | CoinGecko, L2BEAT, Matter Labs</i>"""


async def send_part(bot, channel_id, text, label):
    try:
        await bot.send_message(chat_id=channel_id, text=text, parse_mode=ParseMode.HTML)
        logger.info(f"{label} sent!")
        await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"{label} failed: {e}")
        try:
            safe = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
            await bot.send_message(chat_id=channel_id, text=safe)
            logger.info(f"{label} sent without HTML")
            await asyncio.sleep(1)
        except Exception as e2:
            logger.error(f"{label} retry failed: {e2}")


async def run():
    bot = get_bot()
    channel_id = config.telegram.channel_id

    if not channel_id:
        logger.error("TELEGRAM_CHANNEL_ID not set!")
        return

    logger.info(f"Sending ZKsync report to {channel_id}...")

    await send_part(bot, channel_id, ZK_1, "ZK Part 1")
    await send_part(bot, channel_id, ZK_2, "ZK Part 2")
    await send_part(bot, channel_id, ZK_3, "ZK Part 3")
    await send_part(bot, channel_id, ZK_4, "ZK Part 4")

    logger.info("ZKsync report complete!")


if __name__ == "__main__":
    asyncio.run(run())
