import re


def detect_subscribe_type(name: str) -> str:
    name = name.strip().upper()

    if re.match(r"[А-ЯЁA-Z0-9]{2,}-\d{2}-\d{2}", name):
        return "group"

    if re.match(r"^[А-ЯA-Z]-\d{1,4}$", name):
        return "place"

    if re.match(r"^\d{1,4}$", name):
        return "place"

    if re.search(r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.?(\s*[А-ЯЁ]\.)?", name) or len(name.split()) == 1:
        return "teacher"

    return "teacher"