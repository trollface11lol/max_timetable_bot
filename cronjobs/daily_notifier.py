import asyncio
import logging
import os
from datetime import datetime, timedelta
from sqlalchemy import text as sql_text

from handlers.days_handler import to_unix_timestamp
from db.db_operations import get_db_session, get_lessons, get_user_subscriptions, merge_duplicate_lessons
from utils.messaging import send_message, split_long_message


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DB_PATH = os.getenv("SQLITE_PATH")


async def build_schedule_text(peer_id: int) -> str:
    subs = await get_user_subscriptions(peer_id)
    if not subs or not any(subs.values()):
        return "❌ У вас нет активных подписок."

    date_start = datetime.now().date()
    start_ts = to_unix_timestamp(date_start)
    end_ts = to_unix_timestamp(date_start, end_of_day=True)

    text = f"📅 Расписание на сегодня ({date_start.strftime('%d.%m.%Y')}):\n\n"
    emoji_map = {"group": "👥", "teacher": "👨‍🏫", "place": "🏫"}

    for stype, ids in subs.items():
        for sid in ids:
            lessons = get_lessons(
                DB_PATH,
                **{f"{stype}_id": sid},
                start_ts=start_ts,
                end_ts=end_ts
            )
            if not lessons:
                continue

            lessons = merge_duplicate_lessons(lessons)
            title = lessons[0].get(
                {"teacher": "teacher", "group": "group_name", "place": "place_name"}[stype]
            )
            text += f"{emoji_map.get(stype, '')} <b>{title}</b>\n\n"

            for lesson in lessons:
                start_time = datetime.fromtimestamp(lesson["start"]) + timedelta(hours=3)
                end_time = datetime.fromtimestamp(lesson["end"]) + timedelta(hours=3)
                time_str = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"

                teachers = [t for t in lesson.get("teachers", []) if t and t.lower() != "не указан" and t != title]
                groups = [g for g in lesson.get("groups", []) if g and g.lower() != "не указана" and g != title]
                places = [(p[0], p[1]) for p in lesson.get("places", []) if p[0] and p[0].lower() != "не указано" and p[0] != title]

                if not (teachers or groups or places):
                    continue

                text += f"🕒 {time_str} — {lesson['discipline']} ({lesson['lesson_type']})\n"
                if teachers:
                    text += f"👨‍🏫 {', '.join(teachers)}\n"
                if places:
                    text += f"🏫 {', '.join([f'{p[0]} ({p[1]})' for p in places])}\n"
                if groups:
                    text += f"👥 {', '.join(groups)}\n"
                text += "\n"
            text += "\n"

    return text.strip() or "✅ На сегодня занятий нет!"


async def daily_notifier():
    logger.info("Daily notifier started")
    try:
        async with get_db_session() as session:
            result = await session.execute(sql_text(
                "SELECT chat_id FROM max_subscribes WHERE everyday_nots IS TRUE"
            ))
            rows = result.all()
            logger.info(f"Found {len(rows)} rows with everyday_nots = true")
    except Exception as e:
        logger.exception("Failed to fetch subscribers")
        return

    for row in rows:
        peer_id = row[0]
        try:
            message_text = await build_schedule_text(peer_id)
            if not message_text:
                logger.info(f"No message for {peer_id}")
                continue

            for chunk in split_long_message(message_text):
                await send_message(peer_id, chunk)

        except Exception as e:
            logger.exception(f"Error processing peer_id={peer_id}: {e}")

    logger.info("Daily notifier finished")


if __name__ == "__main__":
    asyncio.run(daily_notifier())
