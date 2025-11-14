import os
from maxapi import Router, F
from maxapi.types import MessageCreated, MessageCallback, CallbackButton, ButtonsPayload, Command, NewMessageLink
from maxapi.context.context import MemoryContext
from datetime import datetime, timedelta

from db.db_operations import get_user_subscriptions, find_entity_by_name, get_campus_by_place_id, \
    get_entity_name_by_type, get_lessons, send_schedule_message
from utils.detect import detect_subscribe_type

DB_PATH = os.getenv("SQLITE_PATH")

day_handler = Router()
user_contexts: dict[int, MemoryContext] = {}


def to_unix_timestamp(dt: datetime.date, end_of_day=False):
    dt_time = datetime.combine(dt, datetime.max.time() if end_of_day else datetime.min.time())
    return int(dt_time.timestamp())


def get_context(chat_id: int) -> MemoryContext:
    if chat_id not in user_contexts:
        user_contexts[chat_id] = MemoryContext(chat_id, chat_id)
    return user_contexts[chat_id]


@day_handler.message_created(Command("today"))
async def cmd_today(event: MessageCreated):
    await handle_schedule_command(event, "today")


@day_handler.message_created(Command("tomorrow"))
async def cmd_tomorrow(event: MessageCreated):
    await handle_schedule_command(event, "tomorrow")


@day_handler.message_created(Command("week"))
async def cmd_week(event: MessageCreated):
    await handle_schedule_command(event, "week")


async def handle_schedule_command(event: MessageCreated, day_type: str):
    chat_id = event.message.recipient.chat_id
    ctx = get_context(chat_id)

    text = event.message.body.text.strip()
    args = text.split(maxsplit=1)

    if len(args) > 1:
        query = args[1].strip()
        detected_type = detect_subscribe_type(query)
        results = find_entity_by_name(detected_type, query)

        if not results:
            await event.message.answer("❌ Ничего не найдено. Проверьте правильность написания.")
            return

        if len(results) > 1:
            txt = "🔍 Найдено несколько совпадений:\n"
            for i, (eid, title) in enumerate(results, 1):
                if detected_type == "place":
                    campus = get_campus_by_place_id(eid)
                    if campus:
                        title = f"{title} ({campus})"
                txt += f"{i}. {title}\n"
            txt += "\n📋 Отправьте номер нужного варианта (только цифру):"

            await ctx.set_state("choosing_from_list")
            await ctx.update_data(search_results=results, sub_type=detected_type, day_type=day_type)
            await event.message.answer(txt)
            return

        entity_id, _ = results[0]
        await _send_schedule(event, entity_id, detected_type, day_type)
        return

    await _show_type_selection(event, day_type)


async def _show_type_selection(event_or_callback, day_type: str):
    chat_id = event_or_callback.message.recipient.chat_id if isinstance(event_or_callback, MessageCallback) else event_or_callback.message.recipient.chat_id
    subs = await get_user_subscriptions(chat_id)

    if not subs or not any(subs.values()):
        await event_or_callback.message.answer("❌ У вас нет активных подписок.")
        return

    total_subs = sum(len(ids) for ids in subs.values() if ids)
    if total_subs == 1:
        for stype, ids in subs.items():
            if ids:
                await _send_schedule(event_or_callback, ids[0], stype, day_type)
                return

    buttons = []
    if "group" in subs and subs["group"]:
        buttons.append([CallbackButton(text="👥 Группы", payload=f"{day_type}_type_group")])
    if "teacher" in subs and subs["teacher"]:
        buttons.append([CallbackButton(text="👨‍🏫 Преподаватели", payload=f"{day_type}_type_teacher")])
    if "place" in subs and subs["place"]:
        buttons.append([CallbackButton(text="🏫 Аудитории", payload=f"{day_type}_type_place")])

    kb = ButtonsPayload(buttons=buttons).pack()
    day_names = {"today": "сегодня", "tomorrow": "завтра", "week": "на неделю"}
    await event_or_callback.message.answer(f"📅 Выберите тип расписания {day_names[day_type]}:", attachments=[kb])


@day_handler.message_callback(F.callback.payload.regexp(r"^(today|tomorrow|week)_(type|schedule)_"))
async def handle_callback(callback: MessageCallback):
    payload = callback.callback.payload
    chat_id = callback.message.recipient.chat_id
    ctx = get_context(chat_id)

    if payload.startswith("back_to_"):
        day_type = payload.split("_")[2]
        await _show_type_selection(callback, day_type)
        await callback.answer()
        return

    if "_type_" in payload:
        day_type, stype = payload.split("_")[0], payload.split("_")[2]
        subs = await get_user_subscriptions(chat_id)
        if not subs.get(stype):
            await callback.message.answer(f"❌ Нет подписок типа {stype}.")
            await callback.answer()
            return

        buttons = []
        for eid in subs[stype]:
            title = await get_entity_name_by_type(DB_PATH, stype, eid)
            emoji = "👥" if stype == "group" else "👨‍🏫" if stype == "teacher" else "🏫"
            buttons.append([CallbackButton(text=f"{emoji} {title}", payload=f"{day_type}_schedule_{stype}_{eid}")])
        buttons.append([CallbackButton(text="⬅️ Назад", payload=f"back_to_{day_type}_main")])

        type_names = {
            "group": "группу",
            "teacher": "преподавателя",
            "place": "аудиторию"
        }

        kb = ButtonsPayload(buttons=buttons).pack()
        await callback.message.answer(
            f"📅 Выберите {type_names.get(stype, stype)}:",
            attachments=[kb],
            link=NewMessageLink(type="reply", mid=callback.message.body.mid)
        )
        await callback.answer()
        await callback.message.delete()
        return

    if "_schedule_" in payload:
        parts = payload.split("_")
        day_type, stype, schedule_id = parts[0], parts[2], int(parts[3])
        await _send_schedule(callback, schedule_id, stype, day_type)
        await callback.answer()
        return


async def _send_schedule(event_or_callback, schedule_id: int, stype: str, day_type: str):
    if day_type == "today":
        date_start = datetime.now().date()
        date_end = date_start
    elif day_type == "tomorrow":
        date_start = datetime.now().date() + timedelta(days=1)
        date_end = date_start
    else:  # week
        monday = datetime.now().date() - timedelta(days=datetime.now().weekday())
        date_start = monday
        date_end = monday + timedelta(days=6)

    start_ts = to_unix_timestamp(date_start)
    end_ts = to_unix_timestamp(date_end, end_of_day=True)

    if stype == "teacher":
        lessons = get_lessons(DB_PATH, teacher_id=schedule_id, start_ts=start_ts, end_ts=end_ts)
    elif stype == "group":
        lessons = get_lessons(DB_PATH, group_id=schedule_id, start_ts=start_ts, end_ts=end_ts)
    elif stype == "place":
        lessons = get_lessons(DB_PATH, place_id=schedule_id, start_ts=start_ts, end_ts=end_ts)
    else:
        lessons = []

    title_map = {"today": "сегодня", "tomorrow": "завтра", "week": "на неделю"}
    await send_schedule_message(event_or_callback, lessons, f"📅 Расписание {title_map[day_type]}", schedule_type=stype)


@day_handler.message_callback(F.callback.payload.regexp(r"^back_to_"))
async def handle_back_button(callback: MessageCallback):
    payload = callback.callback.payload
    parts = payload.split("_")
    if len(parts) >= 3:
        day_type = parts[2]

        await callback.message.delete()

        await _show_type_selection(callback, day_type)

    await callback.answer()
