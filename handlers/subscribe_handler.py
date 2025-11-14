from maxapi import Router, F
from maxapi.types import MessageCreated, MessageCallback, Command, CallbackButton, ButtonsPayload
from maxapi.context.state_machine import StatesGroup, State
from maxapi.context.context import MemoryContext

from db.db_operations import add_subscription, find_entity_by_name, get_campus_by_place_id
from utils.detect import detect_subscribe_type
from utils.keyboards import get_subscribe_type_kb

subscribe_handler = Router()

user_contexts: dict[int, MemoryContext] = {}


def get_context(chat_id: int) -> MemoryContext:
    if chat_id not in user_contexts:
        user_contexts[chat_id] = MemoryContext(chat_id, chat_id)
    return user_contexts[chat_id]


class SubscribeStates(StatesGroup):
    choosing_type = State()
    entering_name = State()
    choosing_from_list = State()


@subscribe_handler.message_created(Command("subscribe"))
async def subscribe_start(event: MessageCreated):
    chat_id = event.message.recipient.chat_id
    ctx = get_context(chat_id)

    text = event.message.body.text or ""
    args = text.split(maxsplit=1)

    if len(args) > 1:
        query = args[1].strip()
        sub_type = detect_subscribe_type(query)
        results = find_entity_by_name(sub_type, query)

        if not results:
            await event.message.answer("❌ Ничего не найдено. Проверьте правильность написания.")
            return

        if len(results) > 1:
            txt = "🔍 Найдено несколько совпадений:\n"
            for i, (eid, title) in enumerate(results, 1):
                if sub_type == "place":
                    campus = get_campus_by_place_id(eid)
                    if campus:
                        title = f"{title} ({campus})"
                txt += f"{i}. {title}\n"
            txt += "\n📋 Отправьте номер нужного варианта (только цифру):"

            await ctx.set_state(SubscribeStates.choosing_from_list)
            await ctx.update_data(search_results=results, sub_type=sub_type)
            await event.message.answer(txt)
            return

        entity_id, entity_name = results[0]
        if sub_type == "place":
            campus = get_campus_by_place_id(entity_id)
            if campus:
                entity_name = f"{entity_name} ({campus})"

        await add_subscription(chat_id, sub_type, entity_id)
        await event.message.answer(f"✅ Подписка оформлена на {entity_name}")
        return

    await ctx.set_state(SubscribeStates.choosing_type)
    kb = get_subscribe_type_kb().pack()
    await event.message.answer(
        text="Выберите тип расписания, на который хотите подписаться:",
        attachments=[kb]
    )


@subscribe_handler.message_callback(F.callback.payload.startswith("subscribe_"))
async def choose_type(callback: MessageCallback):
    chat_id = callback.message.recipient.chat_id
    ctx = get_context(chat_id)

    sub_type = callback.callback.payload.split("_")[1]
    await ctx.update_data(sub_type=sub_type)
    await ctx.set_state(SubscribeStates.entering_name)

    prompts = {
        "group": "Введите название группы (например, ИНБО-03-22):",
        "teacher": "Введите фамилию преподавателя (например, Акатьев Я. А.):",
        "place": "Введите название аудитории (например, Г-112):",
    }

    await callback.message.answer(prompts[sub_type])


@subscribe_handler.message_created(F.message.body.text & ~F.message.body.text.startswith("/"))
async def process_name_or_number(event: MessageCreated):
    chat_id = event.message.recipient.chat_id
    ctx = get_context(chat_id)

    text = event.message.body.text.strip()
    current_state = await ctx.get_state()
    if not current_state:
        return

    data = await ctx.get_data()
    sub_type = data.get("sub_type")

    cancel_kb = ButtonsPayload(
        buttons=[[CallbackButton(text="❌ Отменить поиск", payload="cancel_search")]]
    )

    if current_state == SubscribeStates.choosing_from_list:
        try:
            num = int(text)
            results = data["search_results"]

            if num < 1 or num > len(results):
                await event.message.answer(
                    f"❌ Пожалуйста, выберите номер от 1 до {len(results)}",
                    attachments=[cancel_kb.pack()]
                )
                return

            entity_id, entity_name = results[num - 1]
            if sub_type == "place":
                campus = get_campus_by_place_id(entity_id)
                if campus:
                    entity_name = f"{entity_name} ({campus})"

            await add_subscription(chat_id, sub_type, entity_id)
            await ctx.clear()
            await event.message.answer(f"✅ Подписка оформлена на {entity_name}")
            return

        except ValueError:
            await event.message.answer("❌ Введите корректный номер.", attachments=[cancel_kb.pack()])
            return

    if current_state == SubscribeStates.entering_name:
        results = find_entity_by_name(sub_type, text)
        if not results:
            await event.message.answer("❌ Ничего не найдено, попробуйте уточнить название.",
                                       attachments=[cancel_kb.pack()])
            return

        if len(results) > 1:
            txt = "🔍 Найдено несколько совпадений:\n"
            for i, (eid, title) in enumerate(results, 1):
                if sub_type == "place":
                    campus = get_campus_by_place_id(eid)
                    if campus:
                        title = f"{title} ({campus})"
                txt += f"{i}. {title}\n"
            txt += "\n📋 Отправьте номер нужного варианта (только цифру):"

            await ctx.set_state(SubscribeStates.choosing_from_list)
            await ctx.update_data(search_results=results, sub_type=sub_type)
            await event.message.answer(txt)
            return

        entity_id, entity_name = results[0]
        if sub_type == "place":
            campus = get_campus_by_place_id(entity_id)
            if campus:
                entity_name = f"{entity_name} ({campus})"

        await add_subscription(chat_id, sub_type, entity_id)
        await ctx.clear()
        await event.message.answer(f"✅ Подписка оформлена на {entity_name}")


@subscribe_handler.message_callback(F.callback.payload == "cancel_search")
async def cancel_search(callback: MessageCallback):
    chat_id = callback.message.recipient.chat_id
    ctx = get_context(chat_id)
    await ctx.clear()
    await callback.message.answer("❌ Поиск отменен.")
