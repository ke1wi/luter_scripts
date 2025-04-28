from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

from app.bot.handlers import router as document_router
from app.settings import settings


async def on_startup(bot: Bot, dispatcher: Dispatcher) -> None:
    if (await bot.get_webhook_info()).url != settings.WEBHOOK_URL:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(
            settings.WEBHOOK_URL,
            drop_pending_updates=True,
            secret_token=settings.TELEGRAM_SECRET.get_secret_value(),
            allowed_updates=dispatcher.resolve_used_update_types(),
        )


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(
        events_isolation=SimpleEventIsolation(),
        storage=MemoryStorage(),
    )
    dispatcher.include_routers(document_router)
    dispatcher.startup.register(on_startup)

    return dispatcher


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
