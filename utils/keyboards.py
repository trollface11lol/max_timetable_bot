from maxapi.types import CallbackButton, ButtonsPayload


def get_subscribe_type_kb():
    buttons = [
        [CallbackButton(text="👥 Группа", payload="subscribe_group")],
        [CallbackButton(text="👨‍🏫 Преподаватель", payload="subscribe_teacher")],
        [CallbackButton(text="🏫 Аудитория", payload="subscribe_place")]
    ]
    return ButtonsPayload(buttons=buttons)


def get_subscribe_keyboard():
    buttons = [
        [CallbackButton(text="✅ Подписаться", payload="daily_subscribe")],
        [CallbackButton(text="❌ Отписаться", payload="daily_unsubscribe")]
    ]
    return ButtonsPayload(buttons=buttons).pack()
