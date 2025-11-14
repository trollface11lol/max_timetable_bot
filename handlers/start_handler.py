from maxapi import Router, F
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import MessageCreated

main_handler = Router()


@main_handler.message_created(F.message.body.text == "/start")
async def cmd_start(event: MessageCreated):
    await event.message.answer(
        "🤖 Бот расписания МИРЭА\n\n"
        "Доступные команды:\n"
        "/schedules - Мои подписки\n"
        "/week - На неделю\n"
        "/today - На сегодня\n"
        "/tomorrow - На завтра\n"
        "/subscribe - Подписаться на выбранный тип\n"
        "/unsubscribe - Отписаться\n\n"
        "💡 Также можно использовать:\n"
        "/subscribe ИКБО-01-17 или /subscribe Акатьев Я. А."
    )
