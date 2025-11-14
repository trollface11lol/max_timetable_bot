import logging
import aiohttp
import os


MAX_TOKEN = os.getenv("MAX_BOT_TOKEN")
MAX_API_URL = os.getenv("MAX_API_URL", "https://platform-api.max.ru/messages")


async def send_message(chat_id: int, text: str) -> bool:
    if not chat_id:
        logging.error("❌ chat_id is required")
        return False

    params = {"access_token": MAX_TOKEN, "chat_id": chat_id}
    body = {"text": text, "attachments": None, "link": None, "format": "html"}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(MAX_API_URL, params=params, json=body, timeout=20) as resp:
                resp_text = await resp.text()
                logging.info(f"📤 Sent to {chat_id}: {resp.status} — {resp_text[:200]}")
                return resp.status == 200
        except Exception as e:
            logging.exception(f"⚠️ Error sending to {chat_id}: {e}")
            return False


def split_long_message(text: str, limit: int = 4000) -> list[str]:
    parts, current = [], []
    for line in text.splitlines():
        if sum(len(l) + 1 for l in current) + len(line) > limit:
            parts.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        parts.append("\n".join(current))
    return parts
