import os
import logging
import aiohttp
from typing import List, Dict, Any
from sqlalchemy import text

from db.db_operations import get_db_session
from grpc.schedule_client import ScheduleWebClient
from grpc import personal_schedule_pb2 as pb2
from google.type import dayofweek_pb2
from utils.messaging import send_message, split_long_message


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TOKEN_URL = os.getenv("TOKEN_URL")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
SCHEDULE_URL = os.getenv("SCHEDULE_URL")

TOKEN_DATA = {
    "grant_type": "client_credentials",
    "scope": "openid",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
}


async def fetch_access_token(session: aiohttp.ClientSession) -> str:
    async with session.post(TOKEN_URL, data=TOKEN_DATA) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data["access_token"]


async def get_structured_updates() -> List[Dict[str, Any]]:
    async with aiohttp.ClientSession() as session:
        token = await fetch_access_token(session)
        async with ScheduleWebClient(token) as client:
            schedules = await client.get_subscribed_schedules()
            updates = []

            for schedule in schedules.schedules:
                try:
                    updates_response = await client.get_personal_schedule_updates(schedule.schedule_id)
                    if not updates_response.HasField("exists"):
                        continue

                    diff = updates_response.exists
                    record = {
                        "type": pb2.ScheduleType.Name(schedule.schedule_id.schedule_type),
                        "id": schedule.schedule_id.schedule_id,
                        "title": schedule.long_title,
                        "snapshot_id": diff.snapshot_id,
                        "previous_time": _safe_time(diff, "previous_time"),
                        "current_time": _safe_time(diff, "current_time"),
                        "timetable_changes": [_parse_timetable_diff(td) for td in diff.timetable_diff],
                        "event_changes": [_parse_event_diff(ed) for ed in diff.event_diff],
                    }
                    updates.append(record)
                except Exception as e:
                    logger.exception(f"Ошибка при проверке обновлений для {schedule.long_title}: {e}")
            return updates


def _safe_time(diff, field):
    if diff.HasField(field):
        return getattr(diff, field).ToDatetime().isoformat()
    return None


def _parse_timetable_diff(diff):
    slot = diff.time_slot
    return {
        "time_slot": {
            "day_of_week": dayofweek_pb2.DayOfWeek.Name(slot.day_of_week),
            "number_in_day": slot.number_in_day,
            "week_parity": pb2.WeekParity.Name(slot.week_parity),
        },
        "cells": [
            {k: _extract_lesson_data(getattr(c, k)) for k in ("previous", "current") if c.HasField(k)}
            for c in diff.cells
        ],
    }


def _parse_event_diff(event_diff):
    slot = event_diff.time_slot
    changes = []
    for d in event_diff.diff:
        changes.append({
            "start_time": slot.start.ToDatetime().isoformat() if slot.HasField("start") else None,
            "end_time": slot.end.ToDatetime().isoformat() if slot.HasField("end") else None,
            "previous": _extract_event_data(d.previous) if d.HasField("previous") else None,
            "current": _extract_event_data(d.current) if d.HasField("current") else None,
            "change_type": _determine_event_change_type(d),
        })
    return changes


def _extract_lesson_data(lesson):
    if not lesson:
        return None
    return {
        "discipline": lesson.discipline,
        "lesson_type": lesson.lesson_type.value if lesson.HasField("lesson_type") else None,
        "groups": list(lesson.groups),
        "teachers": list(lesson.teachers),
        "auditoriums": list(lesson.auditoriums),
        "begin_time": lesson.begin_time,
        "end_time": lesson.end_time,
        "time_details": _extract_time_details(lesson),
    }


def _extract_time_details(lesson):
    if not lesson.HasField("time_details"):
        return None
    td = lesson.time_details
    return {"weeks_include": list(td.weeks_include), "weeks_exclude": list(td.weeks_exclude)}


def _extract_event_data(event):
    if not event:
        return None
    return {
        "discipline": event.discipline,
        "lesson_type": event.lesson_type,
        "groups": list(event.groups),
        "teachers": list(event.teachers),
        "auditoriums": list(event.auditoriums),
    }


def _determine_event_change_type(diff_element):
    prev, curr = diff_element.HasField("previous"), diff_element.HasField("current")
    if not prev and curr:
        return "ADDED"
    if prev and not curr:
        return "REMOVED"
    if prev and curr:
        return "MODIFIED"
    return "UNKNOWN"


# === Работа с БД ===
async def get_all_subscriptions() -> list[dict]:
    async with get_db_session() as session:
        result = await session.execute(
            text("SELECT chat_id, teacher_ids, group_ids, auditorium_ids FROM max_subscribes")
        )
        rows = result.mappings().all()
        subs = []
        for row in rows:
            subs.append({
                "peer_id": row["chat_id"],
                "teacher": _split_ids(row["teacher_ids"]),
                "group": _split_ids(row["group_ids"]),
                "place": _split_ids(row["auditorium_ids"]),
            })
        return subs


def _split_ids(raw):
    return [int(x) for x in (raw or "").split(",") if x.isdigit()]


# === Фильтрация изменений ===
def find_relevant_changes_for_chat(changes: list[dict], subs: dict) -> list[dict]:
    mapping = {
        "SCHEDULE_TYPE_TEACHER": subs["teacher"],
        "SCHEDULE_TYPE_GROUP": subs["group"],
        "SCHEDULE_TYPE_PLACE": subs["place"],
    }
    return [ch for ch in changes if ch["id"] in mapping.get(ch["type"], [])]


# === Форматирование ===
def _format_timetable_change(t: dict) -> str:
    time_slot = t["time_slot"]
    num = time_slot["number_in_day"]
    parity = _format_week_parity(time_slot["week_parity"])

    lines = [f"<b>{num} пара ({parity})</b>"]
    for cell in t["cells"]:
        prev, curr = cell.get("previous"), cell.get("current")

        if curr and not prev:
            lines.append("<b>➕ Добавлено:</b>")
            lines.append(_format_lesson_details(curr))

        elif prev and not curr:
            lines.append("<b>➖ Убрано:</b>")
            lines.append(_format_lesson_details(prev))

        elif prev and curr:
            lines.append("<b>✏️ Изменено:</b>")
            lines.append(_format_lesson_details(curr))

    return "\n".join(lines)


def _format_week_parity(week_parity: str) -> str:
    mapping = {
        "WEEK_PARITY_EVEN": "чётная неделя",
        "WEEK_PARITY_ODD": "нечётная неделя",
        "WEEK_PARITY_WEEKLY": "еженедельно",
        "WEEK_PARITY_UNKNOWN": "неизвестно",
    }
    return mapping.get(week_parity, "неизвестно")


def _format_lesson_details(lesson: dict) -> str:
    lines = []
    if lesson.get("discipline"):
        lt = f" ({lesson['lesson_type']})" if lesson.get("lesson_type") else ""
        lines.append(f"📚 {lesson['discipline']}{lt}")
    if lesson.get("groups"):
        lines.append(f"👥 Группа: {', '.join(lesson['groups'])}")
    if lesson.get("teachers"):
        lines.append(f"👨‍🏫 {', '.join(lesson['teachers'])}")
    if lesson.get("auditoriums"):
        lines.append(f"🏫 {', '.join(lesson['auditoriums'])}")
    return "\n".join(lines)


def get_russian_day(day: str) -> str:
    mapping = {
        "MONDAY": "Понедельник",
        "TUESDAY": "Вторник",
        "WEDNESDAY": "Среда",
        "THURSDAY": "Четверг",
        "FRIDAY": "Пятница",
        "SATURDAY": "Суббота",
        "SUNDAY": "Воскресенье",
    }
    return mapping.get(day, day)


async def send_updates_to_chat(chat_id: int, lines: list[str]):
    """Отправка обновлений чата в несколько сообщений, если нужно."""
    text = "\n".join(l for l in lines if l.strip())
    logger.info(f"📩 Preparing to send update to {chat_id}")
    for chunk in split_long_message(text):
        await send_message(chat_id, chunk)
