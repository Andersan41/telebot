"""
send_bera_monad_reports.py — Send BERA and Monad fundamental analysis to Telegram.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import config
from bot.notifier import get_bot
from telegram.constants import ParseMode
from loguru import logger


# ══════════════════════════════════════════════════════════════════
# BERA REPORT
# ══════════════════════════════════════════════════════════════════

BERA_1 = """📊 <b>ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ: BERA (BeraChain)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>📌 Текущие метрики</b>
├ Цена: ~$0.24
├ ATH: $14.99 (−98.4% от пика)
├ Market Cap: ~$60M
├ TVL: ~$3.2B (!!!)
├ Circulating: ~130M / 500M (26%)
├ Застейкано в PoL: 25M+ BERA
├ Распределено наград: $30M+
└ Fear & Greed: 22 (Extreme Fear)

<b>🔥 Удивительный парадокс</b>
MCAP $60M при TVL $3.2B — это <b>аномалия</b>. TVL в 53 раза больше капитализации. Такого не ни одной другой цепочки в крипте. Рынок явно не оценил PoL-механику.

<b>🔧 Токеномика</b>
├ Total supply: 500M BERA
├ Community: 48.9% (244.5M)
├ Investors: 34.3% (171.5M)
├ Core Contributors: 16.8% (84M)
├ Газовый токен + стейкинг
└ BGT (governance) — нетрансферабельный"""

BERA_2 = """🏗 <b>Технология: Proof of Liquidity (PoL)</b>

<b>Что такое BeraChain?</b>
EVM-идентичный L1 на Cosmos SDK с уникальным консенсусом <b>Proof of Liquidity</b>. Вместо классического PoS,这里的 безопасность обеспечивается ЛИКВИДНОСТЬЮ.

<b>Tri-Token модель:</b>
┌────────────┬───────────────────────────────────┐
│ <b>BERA</b>      │ Gas токен, стейкинг, collateral   │
│ <b>BGT</b>      │ Governance, нетрансферабельный   │
│ <b>HONEY</b>    │ Стейблкоин экосистемы            │
└────────────┴───────────────────────────────────┘

<b>Как работает PoL?</b>
1. Пользователи предоставляют ликвидность в DeFi протоколы
2. Получают BGT (governance токен)
3. Делегируют BGT валидаторам
4. Валидаторы направляют награды обратно в пулы
5. <b>Флайwheel:</b> ликвидность → безопасность → награды → больше ликвидности

<b>Преимущества PoL vs классический PoS:</b>
├ Ликвидность = безопасность (а не просто стейкинг)
├ Валидаторы конкурируют за делегацию BGT
├ Пользователи получают yield ДАЖЕ если не стейкают
├ Нет "мёртвого" стейкинга — capital efficient
└ EVM-идентичный = любые Ethereum-контракты работают без изменений

<b>Ключевые обновления 2026:</b>
├ PoL V2: 33% наград конвертируется в WBERA → стейкеры BERA
├ Bectra hard fork: первая EVM-сеть с Pectra-апгрейдом
├ BBB (Bera Builds Businesses): фокус на реальный revenue
└ BGT emission снижен с 8% до 5% annually"""

BERA_3 = """🎯 <b>Катализаторы и риски</b>

<b>✅ Катализаторы ЗА:</b>
├ TVL $3.2B = реальная ликвидность (не фантомная)
├ PoL V2 = прямой yield для BERA стейкеров
├ BBB = pivot от farming к реальному revenue
├ Bectra = Pectra-upgrade (первый L1!)
├ EVM-идентичный = миграция Ethereum-проектов
├ MCAP $60M vs TVL $3.2B = глубокий дискаунт
└ Мем-культура Berachain = вирусный маркетинг

<b>❌ Риски ПРОТИВ:</b>
├ −98% от ATH = damagedpsychology
├ Высокий unlock давление после листинга
├ PoL всё ещё экспериментальная механика
├ Конкуренция: Ethereum L2, Solana, Sui, Aptos
├ Нужны реальные продукты, не только narrative
├ BBB должен доставить revenue ИНАЧЕ TVL испарится
└ Сентимент: Extreme Fear (22/100)"""

BERA_4 = """📈 <b>ПРОГНОЗЫ РОСТА BERA</b>

<b>🔴 Пессимистичный</b>
Цель 2026: $0.15 — $0.25
Цель 2027: $0.10 — $0.20
Цель 2030: $0.05 — $0.15

Сценарий: PoL не оправдывает ожиданий, TVL снижается, BBB не генерирует revenue. Экосистема вымирает как many L1.

<b>🟡 Средний (наиболее вероятный)</b>
Цель 2026: $0.50 — $1.50
Цель 2027: $1.00 — $3.00
Цель 2030: $2.00 — $5.00

Сценарий: PoL V2 привлекает стейкеров, BBB запускает 3-5 рабочих продуктов, TVL стабилен $2-4B, BERA торгуется при MCAP $500M-1.5B. Рост ×5-25 от текущей.

<b>🟢 Оптимистичный</b>
Цель 2026: $3.00 — $5.00
Цель 2027: $5.00 — $10.00
Цель 2030: $10.00 — $20.00+

Сценарий: PoL becomes industry standard. BeraChain = DeFi Hub L1. TVL $10B+, MCAP $5B+. Yield mechanics привлекают институты. Мем-культура + технология = культовый проект.

<b>💰 СТОИТ ЛИ НАБИРАТЬ?</b>

Безусловно, <b>одна из самых интересных возможностей</b> в текущем рынке:

├ ✅ TVL/MCAP = 53x (беспрецедентный дискаунт)
├ ✅ PoL V2 = реальный yield
├ ✅ BBB = pivot к revenue
├ ✅ EVM-идентичный (миграция из Ethereum)
├ ❌ −98% от ATH = нужна вера в восстановление
├ ❌ PoL экспериментальная
└ ❌ Fear & Greed: 22 (покупать когда все боятся?)

<b>Стратегия:</b> DCA в зоне $0.15-0.30, горизонт 12-24 мес, 2-4% портфеля.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<i>⚠️ Не является финансовой рекомендацией. DYOR.</i>"""


# ══════════════════════════════════════════════════════════════════
# MONAD REPORT
# ══════════════════════════════════════════════════════════════════

MON_1 = """📊 <b>ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ: MON (Monad)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>📌 Текущие метрики</b>
├ Цена: ~$0.019
├ ATH: $0.04876 (ноя 2025, −61%)
├ Market Cap: ~$257M
├ FDV: ~$1.9B
├ Circulating: 11.8B / 100B (11.8%)
├ ICO: $0.025 (85,800 участников)
├ Фандинг: $244M (Paradigm, Dragonfly, Coinbase)
└ Mainnet: 24 ноября 2025

<b>🔧 Токеномика</b>
├ Total supply: 100B MON
├ Circulating: 11.8B (11.8%)
├ Locked: 50.6B (50.6%)
├ Следующий unlock: 24 ноября 2026
│  └ 16.6B MON (33.6% от MCAP!)
├ Все инвесторы + команда: cliff до ноября 2026
└ Полный unlock: ноябрь 2029

⚠️ <b>КРИТИЧЕСКИЙ РИСК:</b> 24 ноября 2026 —cliff unlock 33.6% от текущего MCAP. Это может статьliquidation event если экосистема не вырастет достаточно."""

MON_2 = """🏗 <b>Технология: Parallelized EVM</b>

<b>Что такое Monad?</b>
Высокопроизводительный EVM-совместимый L1 с параллельным исполнением транзакций. Цель — Solana-класс производительности с Ethereum-совместимостью.

<b>4 ключевых оптимизации:</b>
┌─────────────────────┬───────────────────────────────────┐
│ <b>MonadBFT</b>          │ Консенсус на базе HotStuff       │
│ <b>Deferred Execution</b>│ Разделение consensus и execution │
│ <b>Parallel Execution</b>│ Параллельная обработка TX        │
│ <b>MonadDB</b>           │ Кастомная state database         │
└─────────────────────┴───────────────────────────────────┘

<b>Производительность:</b>
├ 10,000+ TPS (теоретический пик)
├ ~0.8 секунды финализация
├ Близкие к нулю gas fees
├ ~500ms block time
└ Полная EVM-совместимость (любой контракт работает)

<b>Ключевые отличия от Solana:</b>
├ Monad = EVM (Solidity, Remix, Hardhat — всё работает)
├ Solana = SVM (Rust, Anchor — другой стек)
├ Monad: полная совместимость с Ethereum-экосистемой
├ Solana: свои инструменты и языки
└ Monad: newer, less battle-tested

<b>Катализаторы 2026:</b>
├ MetaMask Money Account (запущен эксклюзивно на Monad)
├ Aave интеграция (в процессе)
├ Nitro Accelerator ($7.5M, Paradigm + Electric Capital)
├ FalconX: tokenized credit на Monad
├ TownSquare: $100M liquidity program (USD1 stablecoin)
└ 300+ проектов в экосистеме"""

MON_3 = """🎯 <b>Катализаторы и риски</b>

<b>✅ Катализаторы ЗА:</b>
├ 10,000+ TPS = Solana-класс производительности
├ EVM = миграция Ethereum-проектов без изменений
├ MetaMask эксклюзив = mainsteam UX
├ Aave интеграция = DeFi credibility
├ $244M фандинг = институциональная поддержка
├ $0.019 vs ICO $0.025 = ниже ICO цены
└ RSI 30 = перепроданность

<b>❌ Риски ПРОТИВ:</b>
├ CLIFF UNLOCK 24.11.2026: 16.6B MON = 33.6% MCAP
├ Только 11.8% supply в обращении
├ −61% от ATH
├ Arthur Hayes: 30%+ supply в unlocks 2026
├ Конкуренция: Solana, Sui, Aptos, Sei
├ Пока нет "killer app" на Monad
└ Пост-ICO distribution pressure"""

MON_4 = """📈 <b>ПРОГНОЗЫ РОСТА MON</b>

<b>🔴 Пессимистичный</b>
Цель 2026: $0.015 — $0.025
Цель 2027: $0.010 — $0.020
Цель 2030: $0.005 — $0.015

Сценарий: November unlock = кровавая баня. Экосистема не растёт, MetaMask не привлекает, TVL ниже $200M. Цена тестирует February low ($0.016).

<b>🟡 Средний (наиболее вероятный)</b>
Цель 2026: $0.03 — $0.06 (до unlock)
Цель 2027: $0.05 — $0.15 (post-unlock recovery)
Цель 2030: $0.10 — $0.50

Сценарий: TVL растёт до $300-400M к Q3, экосистема зрееет, November unlock частично абсорбирован. Рост ×3-25 к 2030.

<b>🟢 Оптимистичный</b>
Цель 2026: $0.08 — $0.15
Цель 2027: $0.20 — $0.50
Цель 2030: $1.00 — $3.00+

Сценарий: Monad становится "EVM Solana". MetaMask + Aave привлекают millions users. TVL $1B+. November unlockabsorbedbecause of ecosystem growth. Рост ×50-150 к 2030.

<b>💰 СТОИТ ЛИ НАБИРАТЬ?</b>

<b>Высокорисковая ставка на EVM-производительность:</b>

├ ✅ Технология доказана (10K TPS в продакшне)
├ ✅ MetaMask эксклюзив = огромный UX advantage
├ ✅ $0.019 < ICO $0.025 = ниже цены всех участников
├ ✅ RSI 30 = техническая перепроданность
├ ❌ November cliff unlock = 33.6% MCAP
├ ❌ Только 11.8% supply circulating
└ ❌ Нужен рост экосистемы до ноября

<b>Стратегия:</b>
├ Покупать до ноября (до unlock)
├ DCA в зоне $0.015-0.025
├ Не более 2-3% портфеля
├ Горизонт: 24+ месяцев (post-unlock)
├ ОБЯЗАТЕЛЬНЫЙ стоп-лосс: $0.012
└ Наблюдать за TVL: если >$300M к Q3 → bullish sign

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<i>⚠️ Не является финансовой рекомендацией. DYOR.</i>"""


# ══════════════════════════════════════════════════════════════════
# COMPARISON TABLE
# ══════════════════════════════════════════════════════════════════

COMPARE = """⚖️ <b>СРАВНЕНИЕ: BERA vs MON</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────┬──────────────────┬──────────────────┐
│              │ <b>BERA</b>            │ <b>MON</b>             │
├──────────────┼──────────────────┼──────────────────┤
│ Тип          │ L1 (Cosmos SDK)  │ L1 (Custom)      │
│ Консенсус    │ Proof of Liquidity│ MonadBFT (HotStuff)│
│ Throughput   │ ~1,000 TPS       │ 10,000+ TPS      │
│ EVM          │ Идентичный       │ Совместимый      │
│ TVL          │ $3.2B            │ ~$100-200M       │
│ MCAP         │ $60M             │ $257M            │
│ TVL/MCAP     │ <b>53x</b>           │ <b>0.5-0.8x</b>       │
│ От ATH       │ −98%             │ −61%             │
│ Unlocks      │ Уже прошёл peak  │ <b>Cliff: ноя 2026</b>│
│ Уникальность │ PoL, Tri-Token   │ Parallel EVM     │
│ Культура     │ Мемы + DeFi      │ Институции + Perf│
└──────────────┴──────────────────┴──────────────────┘

<b>Вывод:</b>
├ <b>BERA</b> = deeper value play (TVL 53x MCAP, yield mechanics)
├ <b>MON</b> = growth play (better tech, worse tokenomics)
├ BERA рискует PoL failure, MON рискует unlock dump
├ BERA = если верите в DeFi-флайwheel
└ MON = если верите в EVM-масштабирование

<i>📅 6 июля 2026 | CoinGecko, Tokenomics, Messari</i>"""


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

    logger.info(f"Sending BERA + MON reports to {channel_id}...")

    # BERA
    await send_part(bot, channel_id, BERA_1, "BERA Part 1")
    await send_part(bot, channel_id, BERA_2, "BERA Part 2")
    await send_part(bot, channel_id, BERA_3, "BERA Part 3")
    await send_part(bot, channel_id, BERA_4, "BERA Part 4")

    # MONAD
    await send_part(bot, channel_id, MON_1, "MON Part 1")
    await send_part(bot, channel_id, MON_2, "MON Part 2")
    await send_part(bot, channel_id, MON_3, "MON Part 3")
    await send_part(bot, channel_id, MON_4, "MON Part 4")

    # COMPARISON
    await send_part(bot, channel_id, COMPARE, "Comparison")

    logger.info("All reports sent!")


if __name__ == "__main__":
    asyncio.run(run())
