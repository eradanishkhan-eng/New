"""
Telegram Premium Referral Bot — Main Entry Point
================================================
Supports both polling (development) and webhook (production) modes.
"""

import asyncio
import logging
import sys
import os

# Add project root to path so all modules resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import config
from firebase import initialize_firebase
from utils.logger import logger

# ── Import all routers ─────────────────────────────────────────────────────────
from handlers.start import router as start_router
from handlers.user import router as user_router
from handlers.referral import router as referral_router
from handlers.premium import router as premium_router
from handlers.admin.dashboard import router as admin_dashboard_router
from handlers.admin.requests import router as admin_requests_router
from handlers.admin.broadcast import router as admin_broadcast_router
from handlers.admin.force_join import router as admin_force_join_router
from handlers.admin.statistics import router as admin_statistics_router
from handlers.admin.settings import router as admin_settings_router
from handlers.admin.admins import router as admin_admins_router
from handlers.admin.users import router as admin_users_router

# ── Import middlewares ─────────────────────────────────────────────────────────
from middlewares.auth import AuthMiddleware
from middlewares.throttling import ThrottlingMiddleware


def create_dispatcher() -> Dispatcher:
    """Build and configure the Aiogram Dispatcher with all routers."""
    dp = Dispatcher(storage=MemoryStorage())

    # ── Register middlewares (order matters) ──────────────────────────────────
    dp.message.middleware(ThrottlingMiddleware())
    dp.message.middleware(AuthMiddleware())

    # ── Register admin routers first (more specific) ──────────────────────────
    dp.include_router(admin_dashboard_router)
    dp.include_router(admin_requests_router)
    dp.include_router(admin_broadcast_router)
    dp.include_router(admin_force_join_router)
    dp.include_router(admin_statistics_router)
    dp.include_router(admin_settings_router)
    dp.include_router(admin_admins_router)
    dp.include_router(admin_users_router)

    # ── Register user routers ─────────────────────────────────────────────────
    dp.include_router(start_router)
    dp.include_router(user_router)
    dp.include_router(referral_router)
    dp.include_router(premium_router)

    return dp


async def on_startup(bot: Bot) -> None:
    """Actions to perform on bot startup."""
    logger.info("=" * 55)
    logger.info("  Telegram Premium Referral Bot Starting...")
    logger.info("=" * 55)

    # Initialize Firebase
    try:
        initialize_firebase()
        logger.info("✅ Firebase connected.")
    except Exception as e:
        logger.critical("❌ Firebase initialization failed: %s", e)
        sys.exit(1)

    # Get bot info
    try:
        bot_info = await bot.get_me()
        logger.info("✅ Bot: @%s (ID: %s)", bot_info.username, bot_info.id)
    except Exception as e:
        logger.error("Failed to get bot info: %s", e)

    # Initialize default admin from env if not in Firebase
    from database import get_all_admin_ids
    try:
        admin_ids = await get_all_admin_ids()
        logger.info("✅ Admins loaded: %s", admin_ids)
    except Exception as e:
        logger.error("Failed to load admins: %s", e)

    # Seed default settings
    try:
        from database import get_settings
        settings = await get_settings()
        logger.info(
            "✅ Settings loaded: min_referral=%s maintenance=%s",
            settings.get("minimum_referral"),
            settings.get("maintenance"),
        )
    except Exception as e:
        logger.error("Failed to load settings: %s", e)

    logger.info("=" * 55)
    logger.info("  Bot is ready and accepting messages!")
    logger.info("=" * 55)


async def on_shutdown(bot: Bot) -> None:
    """Cleanup on shutdown."""
    logger.info("Bot is shutting down...")
    await bot.session.close()
    logger.info("Bot stopped.")


async def run_polling() -> None:
    """Run the bot in long-polling mode (development/simple deployments)."""
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Starting in POLLING mode...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
    finally:
        await bot.session.close()


async def run_webhook() -> None:
    """Run the bot in webhook mode (production deployments)."""
    if not config.WEBHOOK_HOST:
        logger.error("WEBHOOK_HOST is not set. Falling back to polling.")
        await run_polling()
        return

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = create_dispatcher()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    webhook_url = f"{config.WEBHOOK_HOST}{config.WEBHOOK_PATH}"

    # Set webhook
    await bot.set_webhook(
        url=webhook_url,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )
    logger.info("Webhook set: %s", webhook_url)

    # Setup aiohttp app
    app = web.Application()
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=config.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    logger.info("Starting in WEBHOOK mode on port %s...", config.WEBHOOK_PORT)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.WEBHOOK_PORT)
    await site.start()

    # Keep alive
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await bot.session.close()


def main() -> None:
    """Entry point — choose polling or webhook based on config."""
    # Validate config before starting
    try:
        config.validate()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("Please check your .env file.")
        sys.exit(1)

    if config.USE_POLLING:
        asyncio.run(run_polling())
    else:
        asyncio.run(run_webhook())


if __name__ == "__main__":
    main()
