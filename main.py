import asyncio
import os
import logging
from maxapi import Bot, Dispatcher
from maxapi.types import BotCommand
from handlers.start_handler import main_handler
from handlers.subscribe_handler import subscribe_handler
from handlers.schedule_handler import schedule_handler
from handlers.days_handler import day_handler
from handlers.unsubscribe_handler import unsubscribe_handler
from handlers.daily_handler import daily_handler

logging.basicConfig(level=logging.INFO)

MAX_TOKEN = os.getenv("MAX_BOT_TOKEN")

bot = Bot(MAX_TOKEN)
dp = Dispatcher()


async def register_handlers():
    dp.include_routers(daily_handler)
    dp.include_routers(unsubscribe_handler)
    dp.include_routers(day_handler)
    dp.include_routers(main_handler)
    dp.include_routers(schedule_handler)
    dp.include_routers(subscribe_handler)



async def main():
    await register_handlers()
    await bot.change_info(
        commands=[
            BotCommand(name="start", description="Запустить бота"),
            BotCommand(name="today", description="Расписание на сегодня"),
            BotCommand(name="tomorrow", description="Расписание на завтра"),
            BotCommand(name="week", description="Расписание на неделю"),
            BotCommand(name="schedules", description="Показать мои подписки"),
            BotCommand(name="subscribe", description="Подписаться на группу / преподавателя / аудиторию"),
            BotCommand(name="unsubscribe", description="Отписаться от подписки"),
            BotCommand(name="daily", description="Управление ежедневной рассылкой"),
        ]
    )
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
