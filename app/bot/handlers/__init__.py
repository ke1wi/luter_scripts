from aiogram import Router
from app.bot.filters.document import DocumentFilter
from app.bot.filters.admin import AdminFilter
from app.bot.handlers.start import start

from aiogram.filters import CommandStart

from app.bot.handlers.start import start
from app.bot.handlers.document import document

router = Router(name=__name__)

router.message.register(start, CommandStart())
router.message.register(document, DocumentFilter(), AdminFilter())
