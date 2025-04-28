from aiogram.types import Message


async def start(message: Message) -> None:
    await message.answer(f"qq, {message.from_user.id}")
