from maxapi import Router, F
from maxapi.types import MessageCreated, MessageCallback, CallbackButton, ButtonsPayload, Command
from maxapi.context.context import MemoryContext
from db.db_operations import get_user_subscriptions, remove_subscription, get_entity_name_by_type, find_entity_by_name
from utils.detect import detect_subscribe_type
import os

DB_PATH = os.getenv("SQLITE_PATH")

unsubscribe_handler = Router()
user_contexts: dict[int, MemoryContext] = {}


def get_context(chat_id: int) -> MemoryContext:
    if chat_id not in user_contexts:
        user_contexts[chat_id] = MemoryContext(chat_id, chat_id)
    return user_contexts[chat_id]


@unsubscribe_handler.message_created(Command("unsubscribe"))
async def unsubscribe_start(event: MessageCreated):
    message = event.message
    chat_id = message.recipient.chat_id
    ctx = get_context(chat_id)

    args = message.body.text.split(maxsplit=1)
    subs = await get_user_subscriptions(chat_id)
    if not subs or not any(subs.values()):
        await message.answer("❌ У вас нет активных подписок для удаления.")
        return

    if len(args) > 1:
        query = args[1].strip()
        detected_type = detect_subscribe_type(query)
        results = await find_entity_by_name(detected_type, query)
        if not results:
            await message.answer("❌ Подписка не найдена.")
            return
        entity_id, entity_name = results[0]

        success = await remove_subscription(chat_id, detected_type, entity_id)
        if success:
            await message.answer(f"✅ Подписка на {entity_name} успешно удалена.")
        else:
            await message.answer(f"⚠️ Подписка на {entity_name} не найдена или уже была удалена.")
        return

    buttons = []
    if subs.get("group"):
        buttons.append([CallbackButton(text="👥 Группы", payload="unsubscribe_group")])
    if subs.get("teacher"):
        buttons.append([CallbackButton(text="👨‍🏫 Преподаватели", payload="unsubscribe_teacher")])
    if subs.get("place"):
        buttons.append([CallbackButton(text="🏫 Аудитории", payload="unsubscribe_place")])

    kb = ButtonsPayload(buttons=buttons).pack()
    await message.answer("Выберите тип подписки, от которого хотите отписаться:", attachments=[kb])
    await ctx.set_state("choosing_unsubscribe_type")


@unsubscribe_handler.message_callback(F.callback.payload.regexp(r"^unsubscribe_(group|teacher|place)$"))
async def choose_unsubscribe_type(callback: MessageCallback):
    chat_id = callback.message.recipient.chat_id
    ctx = get_context(chat_id)
    sub_type = callback.callback.payload.split("_")[1]

    subs = await get_user_subscriptions(chat_id)
    if not subs.get(sub_type):
        await callback.message.answer("❌ Нет активных подписок этого типа.")
        await callback.answer()
        return

    buttons = []
    for eid in subs[sub_type]:
        title = await get_entity_name_by_type(DB_PATH, sub_type, eid)
        emoji = "👥" if sub_type == "group" else "👨‍🏫" if sub_type == "teacher" else "🏫"
        buttons.append([CallbackButton(text=f"{emoji} {title}", payload=f"unsubscribe_item_{sub_type}_{eid}")])
    buttons.append([CallbackButton(text="❌ Отмена", payload="cancel_unsubscribe")])

    kb = ButtonsPayload(buttons=buttons).pack()
    await callback.message.delete()
    await callback.message.answer("Выберите конкретную подписку, которую хотите удалить:", attachments=[kb])
    await ctx.update_data(sub_type=sub_type)


@unsubscribe_handler.message_callback(F.callback.payload.regexp(r"^unsubscribe_item_"))
async def handle_unsubscribe_item(callback: MessageCallback):
    chat_id = callback.message.recipient.chat_id
    ctx = get_context(chat_id)
    parts = callback.callback.payload.split("_")
    sub_type = parts[2]
    entity_id = int(parts[3])

    title = await get_entity_name_by_type(DB_PATH, sub_type, entity_id)
    success = await remove_subscription(chat_id, sub_type, entity_id)

    if success:
        await callback.message.answer(f"✅ Подписка на {title} успешно удалена.")
    else:
        await callback.message.answer(f"⚠️ Подписка на {title} не найдена или уже была удалена.")

    await callback.message.delete()
    await ctx.clear()


@unsubscribe_handler.message_callback(F.callback.payload == "cancel_unsubscribe")
async def cancel_unsubscribe(callback: MessageCallback):
    chat_id = callback.message.recipient.chat_id
    ctx = get_context(chat_id)
    await callback.message.delete()
    await callback.message.answer("❌ Отмена операции отписки.")
    await ctx.clear()
