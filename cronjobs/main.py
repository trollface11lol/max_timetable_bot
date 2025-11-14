import os
import asyncio
import aiohttp
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from cronjobs.subscribe_by_api import update_schedule_if_needed
from cronjobs.updates_by_api import get_structured_updates, send_updates_to_subscribers
from cronjobs.daily_notifier import daily_notifier
from grpc.schedule_client import ScheduleWebClient
from grpc import personal_schedule_pb2 as pb2

from pytz import timezone


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TOKEN_URL = os.getenv("TOKEN_URL")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

TOKEN_DATA = {
    "grant_type": "client_credentials",
    "scope": "openid",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET
}


async def run_update_schedule():
    try:
        await update_schedule_if_needed()
    except Exception as e:
        logger.exception(f"Ошибка при обновлении расписания: {e}")


async def run_send_updates():
    """Проверка обновлений, рассылка и подтверждение получения"""
    try:
        logger.info("Проверка обновлений и рассылка...")

        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, data=TOKEN_DATA) as resp:
                resp.raise_for_status()
                token = (await resp.json())["access_token"]

            async with ScheduleWebClient(token) as client:
                updates = await get_structured_updates()

                if not updates:
                    logger.info("Нет новых обновлений")
                    return

                await send_updates_to_subscribers(updates)
                logger.info("Обновления отправлены подписчикам")

                for upd in updates:
                    try:
                        schedule_id = upd["id"]
                        snapshot_id = upd["snapshot_id"]
                        if snapshot_id:
                            schedule_id_msg = pb2.ScheduleId(
                                schedule_type=pb2.ScheduleType.Value(upd["type"]),
                                schedule_id=upd["id"]
                            )

                            await client.accept_schedule_updates(
                                schedule_id=schedule_id_msg,
                                snapshot_id=upd["snapshot_id"]
                            )
                            logger.info(f"✅ Приняты обновления для {upd['title']}")
                    except Exception as e:
                        logger.warning(f"Не удалось принять обновление для {upd['title']}: {e}")

    except Exception as e:
        logger.exception(f"Ошибка при отправке обновлений: {e}")


def start_scheduler():
    scheduler = AsyncIOScheduler()

    moscow_tz = timezone('Europe/Moscow')

    scheduler.add_job(
        daily_notifier,
        CronTrigger(hour=8, minute=30, day_of_week="0-5", timezone=moscow_tz),
        id="daily_notifier_0830",
        replace_existing=True,
    )

    scheduler.add_job(
        run_update_schedule,
        CronTrigger(minute="0", timezone=moscow_tz),
        id="schedule_update_hourly",
        replace_existing=True,
    )

    scheduler.add_job(
        run_send_updates,
        CronTrigger(hour="7-20", minute="*/10", timezone=moscow_tz),
        id="send_updates_10min",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Планировщик запущен.")
    return scheduler


async def main():
    try:
        logger.info("Запуск сервиса обновлений расписания...")
        scheduler = start_scheduler()
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Остановка сервиса")
        scheduler.shutdown()
    except Exception as e:
        logger.exception(f"❌ Ошибка: {e}")
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
