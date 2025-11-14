from maxapi import Router, F
from maxapi.types import MessageCreated, MessageCallback, Command
from db.db_operations import update_everyday_notifications
from utils.keyboards import get_subscribe_keyboard

daily_handler = Router()


@daily_handler.message_created(Command('daily'))
async def ask_daily_notification(event: MessageCreated):
    message = event.message

    kb = get_subscribe_keyboard()

    await message.answer(
        "Хотите ли вы подписаться на рассылку расписаний из ваших подписок, "
        "которая будет отправляться ежедневно в 8:30 утра?",
        attachments=[kb]
    )


@daily_handler.message_callback(F.callback.payload.in_(["daily_subscribe", "daily_unsubscribe"]))
async def handle_daily_choice(callback: MessageCallback):
    subscribe = callback.callback.payload == "daily_subscribe"
    chat_id = callback.message.recipient.chat_id

    await update_everyday_notifications(chat_id, subscribe)

    text = (
        "✅ Вы подписались на ежедневную рассылку!"
        if subscribe
        else "❌ Ежедневная рассылка отключена."
    )
    await callback.message.delete()
    await callback.message.answer(text=text)
