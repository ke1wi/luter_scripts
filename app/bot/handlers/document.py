from aiogram.types import Message, Document
from aiogram.types.input_file import FSInputFile
from tempfile import NamedTemporaryFile
from loguru import logger
import os
from app.scripts.number_script import NumberScript
import httpx
from typing import Optional


async def document(message: Message, file: Document):
    """Обработчик текстовых файлов для извлечения данных"""
    if not file.file_name.endswith(".txt"):
        await message.answer("Пожалуйста, отправьте файл в формате .txt")
        return

    temp_file_path: Optional[str] = None

    try:
        # Уведомление пользователя
        processing_msg = await message.answer("⏳ Начинаю обработку файла...")

        # Скачивание файла
        document = await message.bot.get_file(file.file_id)
        file_path = document.file_path

        # Создание временного файла
        with NamedTemporaryFile(mode="w+b", delete=False, suffix=".txt") as temp_file:
            temp_file_path = temp_file.name
            await message.bot.download_file(file_path, temp_file.name)

        # Обработка файла
        try:
            result = await NumberScript().run(temp_file_path)
        except httpx.HTTPError as e:
            logger.error(f"API error: {e}")
            await message.answer(
                "⚠️ Ошибка подключения к сервису обработки. Попробуйте позже."
            )
            return
        except Exception as e:
            logger.error(f"Processing error: {e}")
            await message.answer("❌ Ошибка при обработке данных в файле.")
            return

        # Отправка обработанного файла
        try:
            await message.answer_document(
                FSInputFile(temp_file_path, filename=f"processed_{file.file_name}"),
                caption=f"✅ Обработанный файл готов!\n🔍 Запросов на Химеру: {result.himera_api_reqs} ({result.tokens_taken})\n💾 С базы: {result.base_hits}",
            )
        except Exception as e:
            logger.error(f"File sending error: {e}")
            await message.answer("⚠️ Не удалось отправить обработанный файл.")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await message.answer("❌ Произошла непредвиденная ошибка. Попробуйте позже.")
    finally:
        # Удаление временного файла
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file: {e}")

        # Удаление сообщения о обработке
        try:
            await processing_msg.delete()
        except:
            pass
