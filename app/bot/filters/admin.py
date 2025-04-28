from typing import Union

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
from loguru import logger

from app.settings import settings


class AdminFilter(Filter):
    async def __call__(self, update: Union[Message, CallbackQuery]) -> int | None:
        if isinstance(update, Message) and update.from_user.id:
            user_id = update.from_user.id
            if user_id in settings.ADMIN_IDS:
                logger.success("Admin's Request")
                return {"user_id": update.from_user.id}
        elif isinstance(update, CallbackQuery) and update.message.from_user.id:
            user_id = update.message.from_user.id
            if user_id in settings.ADMIN_IDS:
                logger.success("Admin's Request")
                return {"user_id": update.message.from_user.id}
        else:
            return None
