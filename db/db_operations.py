import sqlite3
from typing import List, Dict
import logging
from contextlib import asynccontextmanager
from datetime import datetime
import os
from dotenv import load_dotenv
from datetime import timedelta

from sqlalchemy.exc import SQLAlchemyError

from db.db_tables import MaxSubscribe

from maxapi.enums.parse_mode import ParseMode

from sqlalchemy import select, text
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

load_dotenv()

DB_PATH = os.getenv("SQLITE_PATH")

url = URL.create(
    drivername=os.getenv("DB_DRIVER"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASS"),
    database=os.getenv("DB_NAME")
)

engine = create_async_engine(
    url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)

async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False
)

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


@asynccontextmanager
async def get_db_session():
    """Контекстный менеджер для получения сессии"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()


def merge_duplicate_lessons(lessons: list) -> list:
    """Объединяет дублирующиеся уроки по lesson_id, собирая все группы, преподавателей и аудитории."""
    merged = {}
    for lesson in lessons:
        lid = lesson["lesson_id"]
        if lid not in merged:
            merged[lid] = lesson.copy()
            merged[lid]["teachers"] = [lesson["teacher"]] if lesson["teacher"] else []
            merged[lid]["groups"] = [lesson["group_name"]] if lesson["group_name"] else []
            merged[lid]["places"] = [(lesson["place_name"], lesson["campus"])] if lesson["place_name"] else []
        else:
            if lesson["teacher"] and lesson["teacher"] not in merged[lid]["teachers"]:
                merged[lid]["teachers"].append(lesson["teacher"])
            if lesson["group_name"] and lesson["group_name"] not in merged[lid]["groups"]:
                merged[lid]["groups"].append(lesson["group_name"])
            if lesson["place_name"] and (lesson["place_name"], lesson["campus"]) not in merged[lid]["places"]:
                merged[lid]["places"].append((lesson["place_name"], lesson["campus"]))
    return list(merged.values())


async def send_schedule_message(callback_or_message, lessons, title: str, schedule_type):
    lessons = merge_duplicate_lessons(lessons)

    if hasattr(callback_or_message, "data"):  # MessageCallback
        callback = callback_or_message
        message = callback.message
    else:
        callback = None
        message = callback_or_message.message

    if not lessons:
        text = f"✅ {title}: нет занятий!"
        await message.answer(text)
        if callback:
            await callback.answer()
        return

    if not schedule_type:
        first = lessons[0]
        if first.get("group_name"):
            schedule_type = "group"
        elif first.get("teacher"):
            schedule_type = "teacher"
        elif first.get("place_name"):
            schedule_type = "place"

    grouped = {}
    for lesson in lessons:
        start_dt = datetime.fromtimestamp(lesson["start"])
        end_dt = datetime.fromtimestamp(lesson["end"])
        date_str = start_dt.date().strftime("%d.%m")
        weekday = WEEKDAYS[start_dt.weekday()]
        key = f"{date_str} ({weekday})"
        grouped.setdefault(key, []).append({**lesson, "start_dt": start_dt, "end_dt": end_dt})

    if schedule_type == "group":
        subject_name = lessons[0].get("group_name")
        final_title = f"<b>{title} для {subject_name}</b>"
    elif schedule_type == "teacher":
        subject_name = lessons[0].get("teacher")
        final_title = f"<b>{title} для {subject_name}</b>"
    elif schedule_type == "place":
        subject_name = lessons[0].get("place_name")
        final_title = f"<b>{title} для {subject_name}</b>"
    else:
        final_title = f"📅 {title}"

    text = f"{final_title}\n\n"

    for day, day_lessons in sorted(grouped.items()):
        text += f"<b>{day}</b>\n\n"
        for lesson in day_lessons:
            start_time = lesson["start_dt"] + timedelta(hours=3)
            end_time = lesson["end_dt"] + timedelta(hours=3)
            time_str = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"

            teachers = [t for t in lesson["teachers"] if t and t != "Не указан"]
            groups = [g for g in lesson["groups"] if g and g != "Не указана"]
            places = [(p[0], p[1]) for p in lesson["places"] if p[0] and p[0] != "Не указано"]

            if schedule_type == "teacher":
                teachers = [t for t in teachers if t.lower() != lesson.get("teacher", "").lower()]
            elif schedule_type == "group":
                groups = [g for g in groups if g.lower() != lesson.get("group_name", "").lower()]
            elif schedule_type == "place":
                places = [p for p in places if p[0].lower() != lesson.get("place_name", "").lower()]

            text += f"🕒 {time_str} — {lesson['discipline']} ({lesson['lesson_type']})\n"
            if teachers:
                text += f"👨‍🏫 {', '.join(teachers)}\n"
            if places:
                text += f"🏫 {', '.join([f'{p[0]} ({p[1]})' for p in places])}\n"
            if groups:
                text += f"👥 {', '.join(groups)}\n"
            text += "\n"

    await message.answer(text.strip(), parse_mode=ParseMode.HTML)
    if callback:
        await callback.answer()



def get_lessons(
    db_path: str,
    teacher_id: int = None,
    group_id: int = None,
    place_id: int = None,
    start_ts: int = None,
    end_ts: int = None
) -> List[Dict]:
    """
    Универсальная функция для получения уроков.
    Фильтры опциональные — если нет привязки, будет всё равно возвращать урок.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
    SELECT 
        l.id AS lesson_id,
        l.start,
        l.end,
        d.title AS discipline,
        lt.title AS lesson_type,
        t.name AS teacher,
        ag.title AS group_name,
        p.title AS place_name,
        p.campus
    FROM lesson l
    JOIN discipline d ON l.discipline_id = d.id
    JOIN lesson_type lt ON l.lesson_type_id = lt.id
    LEFT JOIN lesson_teacher ltch ON l.id = ltch.lesson_id
    LEFT JOIN teacher t ON ltch.teacher_id = t.id
    LEFT JOIN lesson_academic_group lag ON l.id = lag.lesson_id
    LEFT JOIN academic_group ag ON lag.academic_group_id = ag.id
    LEFT JOIN lesson_place lp ON l.id = lp.lesson_id
    LEFT JOIN place p ON lp.place_id = p.id
    WHERE 1=1
    """

    params = []
    if teacher_id is not None:
        query += " AND t.id = ?"
        params.append(teacher_id)
    if group_id is not None:
        query += " AND ag.id = ?"
        params.append(group_id)
    if place_id is not None:
        query += " AND p.id = ?"
        params.append(place_id)
    if start_ts is not None:
        query += " AND l.start >= ?"
        params.append(start_ts)
    if end_ts is not None:
        query += " AND l.end <= ?"
        params.append(end_ts)

    query += " ORDER BY l.start"

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()

    lessons = []
    for row in rows:
        lessons.append({
            "lesson_id": row[0],
            "start": row[1],
            "end": row[2],
            "discipline": row[3],
            "lesson_type": row[4],
            "teacher": row[5] or "Не указан",
            "group_name": row[6] or "Не указана",
            "place_name": row[7] or "Не указано",
            "campus": row[8] or "Не указан",
        })
    return lessons



async def get_user_subscriptions(chat_id: int) -> dict:
    """Возвращает словарь { 'group': [...], 'teacher': [...], 'place': [...] }"""
    async with get_db_session() as session:
        result = await session.execute(text("""
            SELECT teacher_ids, group_ids, auditorium_ids
            FROM max_subscribes
            WHERE chat_id = :chat_id
        """), {"chat_id": chat_id})
        row = result.mappings().first()
        if not row:
            return {}

        return {
            "teacher": [int(x) for x in (row["teacher_ids"] or "").split(",") if x.isdigit()],
            "group": [int(x) for x in (row["group_ids"] or "").split(",") if x.isdigit()],
            "place": [int(x) for x in (row["auditorium_ids"] or "").split(",") if x.isdigit()],
        }


async def get_entity_name_by_type(db_path: str, sub_type: str, entity_id: int) -> str:
    """Получает название сущности по ID и типу"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    if sub_type == "group":
        table = "academic_group"
        field = "title"
    elif sub_type == "teacher":
        table = "teacher"
        field = "name"
    elif sub_type == "place":
        table = "place"
        field = "title"
    else:
        raise ValueError("Неверный тип подписки")

    query = f"SELECT {field} FROM {table} WHERE id = ?"
    c.execute(query, (entity_id,))
    result = c.fetchone()
    conn.close()

    return result[0] if result else f"Неизвестно (ID {entity_id})"


async def add_subscription(chat_id: int, sub_type: str, item_id: int):
    """Добавляет подписку пользователя в PostgreSQL."""
    async with get_db_session() as session:
        try:
            # Маппинг названий для разных типов подписок
            field_map = {
                "group": "group_ids",
                "teacher": "teacher_ids",
                "place": "auditorium_ids",
            }
            field_name = field_map[sub_type]

            result = await session.execute(
                select(MaxSubscribe).where(MaxSubscribe.chat_id == chat_id)
            )
            record = result.scalar_one_or_none()

            if not record:
                record = MaxSubscribe(chat_id=chat_id)
                setattr(record, field_name, str(item_id))
                session.add(record)
            else:
                field = getattr(record, field_name, "") or ""
                existing = [x.strip() for x in field.split(",") if x.strip()]
                if str(item_id) not in existing:
                    existing.append(str(item_id))
                    setattr(record, field_name, ",".join(existing))

            await session.commit()

        except SQLAlchemyError as e:
            logger.info(f"❌ Ошибка при добавлении подписки: {e}")


async def remove_subscription(chat_id: int, sub_type: str, item_id: int):
    """Удаляет подписку пользователя из PostgreSQL. Если подписок не осталось — удаляет всю запись."""
    async with get_db_session() as session:
        try:
            field_map = {
                "group": "group_ids",
                "teacher": "teacher_ids",
                "place": "auditorium_ids",
            }
            field_name = field_map[sub_type]

            result = await session.execute(
                select(MaxSubscribe).where(MaxSubscribe.chat_id == chat_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return False

            field_value = getattr(record, field_name, "") or ""
            items = [x.strip() for x in field_value.split(",") if x.strip()]

            if str(item_id) in items:
                items.remove(str(item_id))
                setattr(record, field_name, ",".join(items))

                if not any([
                    getattr(record, "group_ids", None),
                    getattr(record, "teacher_ids", None),
                    getattr(record, "auditorium_ids", None)
                ]):
                    await session.delete(record)
                    logger.info(f"🧹 Все подписки удалены для chat_id={chat_id}, запись очищена.")
                await session.commit()
                return True

            return False

        except SQLAlchemyError as e:
            logger.error(f"❌ Ошибка при удалении подписки: {e}")
            return False



def find_entity_by_name(sub_type: str, name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if sub_type == "group":
        table = "academic_group"
        field = "title"
    elif sub_type == "teacher":
        table = "teacher"
        field = "name"
    elif sub_type == "place":
        table = "place"
        field = "title"
    else:
        raise ValueError("Неверный тип подписки")

    exact_query = f"SELECT id, {field} FROM {table} WHERE {field} = ? COLLATE NOCASE"
    c.execute(exact_query, (name,))
    results = c.fetchall()

    if not results:
        like_query = f"SELECT id, {field} FROM {table} WHERE {field} LIKE ? COLLATE NOCASE"
        c.execute(like_query, (f"%{name}%",))
        results = c.fetchall()

    conn.close()
    return results


def get_campus_by_place_id(place_id: int) -> str | None:
    """
    Возвращает название кампуса по ID аудитории.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT campus FROM place WHERE id = ?", (place_id,))
    row = c.fetchone()

    conn.close()
    return row[0] if row and row[0] else None


async def update_everyday_notifications(chat_id: int, value: bool) -> bool:
    """
    Обновляет флаг ежедневных уведомлений у пользователя.
    Возвращает True при успехе, False при ошибке.
    """
    async with get_db_session() as session:
        try:
            await session.execute(
                text("""
                    UPDATE max_subscribes
                    SET everyday_nots = :val
                    WHERE chat_id = :cid
                """),
                {"val": value, "cid": chat_id}
            )
            await session.commit()
            logger.info(f"🔔 everyday_nots обновлён для chat_id={chat_id}: {value}")
            return True
        except SQLAlchemyError as e:
            logger.error(f"❌ Ошибка при обновлении everyday_nots: {e}")
            await session.rollback()
            return False
