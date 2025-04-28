from typing import Union

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message


class DocumentFilter(Filter):
    async def __call__(self, update: Union[Message, CallbackQuery]) -> dict | None:
        if isinstance(update, Message) and update.document:
            return {"file": update.document}
        elif isinstance(update, CallbackQuery) and update.message and update.message.document:
            return {"file": update.message.document}
        else:
            return None
