import aiohttp
import sqlite3
from grpc.schedule_client import ScheduleWebClient, create_schedule_id
from db.db_operations import get_db_session
from sqlalchemy import text
from typing import List
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

load_dotenv()

DB_PATH = os.getenv("SQLITE_PATH")
TOKEN_URL = os.getenv("TOKEN_URL")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
SCHEDULE_URL = os.getenv("SCHEDULE_URL")

TOKEN_DATA = {
    "grant_type": "client_credentials",
    "scope": "openid",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET
}

TABLES = {
    "teacher": ("teacher", 2),
    "group": ("academic_group", 1),
    "place": ("place", 3),
}


async def get_snapshot_info() -> int:
    """Получает текущий snapshot_id из PostgreSQL"""
    try:
        async with get_db_session() as session:
            result = await session.execute(text("SELECT snapshot_id FROM snapshot_info LIMIT 1"))
            row = result.mappings().first()
            return row["snapshot_id"] if row else 0
    except Exception as e:
        logger.error(f"Ошибка при получении snapshot_id из БД: {e}")
        return 0


async def update_snapshot_id(snapshot_id: int):
    """Обновляет snapshot_id в PostgreSQL"""
    try:
        async with get_db_session() as session:
            result = await session.execute(text("SELECT COUNT(*) as count FROM snapshot_info"))
            count = result.scalar()

            if count == 0:
                await session.execute(text("INSERT INTO snapshot_info (snapshot_id) VALUES (:snapshot_id)"),
                                      {"snapshot_id": snapshot_id})
            else:
                await session.execute(text("UPDATE snapshot_info SET snapshot_id = :snapshot_id"),
                                      {"snapshot_id": snapshot_id})

            await session.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении snapshot_id: {e}")
        raise


def get_all_ids_from_table(table: str) -> List[int]:
    """Получает все ID из SQLite таблицы"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(f'SELECT id FROM "{table}"')
        ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        return ids
    except Exception as e:
        logger.error(f"Ошибка при получении ID из таблицы {table}: {e}")
        return []


async def fetch_access_token(session: aiohttp.ClientSession) -> str:
    """Получает access token"""
    try:
        async with session.post(TOKEN_URL, data=TOKEN_DATA) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["access_token"]
    except Exception as e:
        logger.error(f"Ошибка при получении access token: {e}")
        raise


async def fetch_schedule_info(session: aiohttp.ClientSession, token: str) -> dict:
    """Получает информацию о расписании"""
    try:
        headers = {"Authorization": f"Bearer {token}"}
        async with session.get(SCHEDULE_URL, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
            logger.info(f"Информация о расписании получена, snapshot: {data.get('snapshotId')}")
            return data
    except Exception as e:
        logger.error(f"Ошибка при получении информации о расписании: {e}")
        raise


async def download_db_file(session: aiohttp.ClientSession, db_url: str):
    """Скачивает и сохраняет SQLite файл"""
    try:
        temp_db_path = DB_PATH + ".temp"
        async with session.get(db_url) as resp:
            resp.raise_for_status()
            content = await resp.read()

            with open(temp_db_path, "wb") as f:
                f.write(content)

            if os.path.exists(DB_PATH):
                os.remove(DB_PATH)
            os.rename(temp_db_path, DB_PATH)

        file_size = len(content) / (1024 * 1024)
        logger.info(f"SQLite файл обновлен. Размер: {file_size:.2f} МБ")

    except Exception as e:
        logger.error(f"Ошибка при скачивании SQLite файла: {e}")
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
        raise


async def update_subscriptions(token: str):
    """Обновляет подписки на все расписания"""
    try:
        async with ScheduleWebClient(token) as client:
            all_schedule_ids = []

            for table_name, (db_table, schedule_type) in TABLES.items():
                ids = get_all_ids_from_table(db_table)
                all_schedule_ids.extend([create_schedule_id(schedule_type, schedule_id) for schedule_id in ids])

            logger.info(f"Всего расписаний для подписки: {len(all_schedule_ids)}")

            if not all_schedule_ids:
                logger.warning("Нет расписаний для подписки")
                return

            batch_size = 10000
            total_batches = (len(all_schedule_ids) + batch_size - 1) // batch_size
            successful_batches = 0

            for i in range(0, len(all_schedule_ids), batch_size):
                batch = all_schedule_ids[i:i + batch_size]
                batch_num = (i // batch_size) + 1

                logger.info(f"Отправка батча {batch_num}/{total_batches} ({len(batch)} расписаний)")

                try:
                    response = await client.update_subscribed_schedules(batch)

                    if response and response.state == response.UPDATE_SUBSCRIBED_SCHEDULES_RESPONSE_OK:
                        successful_batches += 1
                        logger.info(f"Батч {batch_num} успешно обработан")
                    else:
                        logger.error(f"Ошибка в батче {batch_num}")

                except Exception as e:
                    logger.error(f"Исключение в батче {batch_num}: {e}")

            logger.info(f"Подписки обновлены. Успешных батчей: {successful_batches}/{total_batches}")

    except Exception as e:
        logger.error(f"Критическая ошибка при обновлении подписок: {e}")
        raise


async def update_schedule_if_needed():
    """Основная функция проверки и обновления расписания"""
    try:
        async with aiohttp.ClientSession() as session:
            token = await fetch_access_token(session)

            schedule_info = await fetch_schedule_info(session, token)
            new_snapshot_id = schedule_info["snapshotId"]
            db_file_url = schedule_info["dbFileLink"]

            current_snapshot = await get_snapshot_info()
            logger.info(f"Snapshot: текущий={current_snapshot}, новый={new_snapshot_id}")

            if new_snapshot_id <= current_snapshot:
                logger.info("Обновлений нет")
                return

            logger.info(f"Найдено обновление! Скачиваем snapshot {new_snapshot_id}")

            await download_db_file(session, db_file_url)
            await update_snapshot_id(new_snapshot_id)
            await update_subscriptions(token)

            logger.info(f"Обновление завершено для snapshot {new_snapshot_id}")

    except Exception as e:
        logger.error(f"Критическая ошибка в основном процессе: {e}")
