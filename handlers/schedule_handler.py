from maxapi import Router
from maxapi.types import MessageCreated, Command
import os

from db.db_operations import get_user_subscriptions, get_entity_name_by_type, get_campus_by_place_id


DB_PATH = os.getenv("SQLITE_PATH")

schedule_handler = Router()


@schedule_handler.message_created(Command('schedules'))
async def cmd_schedules(event: MessageCreated):
    chat_id = event.message.recipient.chat_id

    subs = await get_user_subscriptions(chat_id)
    if not subs:
        await event.message.answer("❌ У вас нет активных подписок.")
        return

    text = "📅 Ваши подписки:\n\n"
    for stype, ids in subs.items():
        if not ids:
            continue
        for eid in ids:
            title = await get_entity_name_by_type(DB_PATH, stype, eid)
            emoji = "👥" if stype == "group" else "👨‍🏫" if stype == "teacher" else "🏫"
            if stype == "place":
                campus = get_campus_by_place_id(eid)
                if campus:
                    text += f"{emoji} {title} ({campus})"
            else:
                text += f"{emoji} {title}\n"

    await event.message.answer(text)
