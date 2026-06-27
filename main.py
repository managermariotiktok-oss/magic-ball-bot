import asyncio
import os
import logging
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from groq import AsyncGroq
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery,
)
from aiogram.filters import CommandStart
from aiogram.enums import ChatAction, ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = "".join(os.environ["TELEGRAM_BOT_TOKEN"].split())
GROQ_API_KEY       = "".join(os.environ["GROQ_API_KEY"].split())

groq_client = AsyncGroq(api_key=GROQ_API_KEY)
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

BTN_TODAY  = "🔮 Предсказание на сегодня"
BTN_WEEK   = "🌙 Предсказание на неделю"
BTN_CARD   = "🎴 Карта дня"
BTN_RITUAL = "🕯️ Ритуал дня"
BTN_ASK    = "👁 Задать вопрос шару"
ALL_BTNS   = {BTN_TODAY, BTN_WEEK, BTN_CARD, BTN_RITUAL, BTN_ASK}

SEP_TODAY  = "🔮  ───────────────  🔮"
SEP_WEEK   = "🌙  ───────────────  🌙"
SEP_CARD   = "🎴  ───────────────  🎴"
SEP_RITUAL = "🕯️  ────────────────  🕯️"
SEP_ASK    = "👁  ───────────────  👁"
SEP_END    = "✦  ───────────────  ✦"
SEP_PAY    = "⭐  ───────────────  ⭐"

PRICES = {"week": 50, "ritual": 30, "question": 15, "unlimited": 200}
FREE_LIMITS = {"today": 1, "card": 1, "questions": 3}

INVOICE_META = {
    "week":      ("🌙 Предсказание на неделю",  "Мистическое видение на семь дней вперёд — шар раскроет тайны судьбы.",         PRICES["week"]),
    "ritual":    ("✨ Ритуал дня",               "Уникальный магический ритуал, который поможет твоим желаниям сбыться сегодня.", PRICES["ritual"]),
    "question":  ("❓ Вопрос шару",              "Личный мистический ответ на твой вопрос — прямо сейчас.",                      PRICES["question"]),
    "unlimited": ("👑 Безлимит на 30 дней",      "Неограниченный доступ ко всем возможностям шара на 30 дней.",                  PRICES["unlimited"]),
}

_user_usage: dict[int, dict] = {}
_user_subscriptions: dict[int, datetime] = {}
_pending_questions: dict[int, str] = {}
_daily_counter: dict[str, int] = {}
_card_cache: dict[str, str] = {}
_ritual_cache: dict[str, str] = {}

MOODS = {
    "mysterious": {
        "prompt": "Твой тон сегодня особенно загадочен и непроницаем. Говори туманно, с недосказанностью — как будто видишь больше, чем решаешься открыть.",
        "header_today": "🔮 <i>Шар мерцает в темноте... завеса приоткрывается...</i>",
        "header_week":  "🌙 <i>Туман времён рассеивается... семь теней проступают...</i>",
        "header_ask":   "🌫️ <i>Вопрос уходит в глубину... ответ поднимается из тьмы...</i>",
        "signoffs": [
            "🌫️ <i>Больше я не скажу. Остальное — твоя судьба.</i>",
            "🔮 <i>Шар умолкает. Тайна остаётся тайной.</i>",
            "🌙 <i>Слушай тишину — в ней тоже есть ответы.</i>",
        ],
    },
    "warning": {
        "prompt": "Твой тон сегодня серьёзный и предостерегающий. Ты видишь что-то тревожное — важный выбор, опасность или переломный момент. Говори с заботой, но не скрывай правды.",
        "header_today": "⚡ <i>Шар вспыхивает красным... видение требует внимания...</i>",
        "header_week":  "🕯️ <i>Пламя колышется... семь дней таят в себе испытание...</i>",
        "header_ask":   "⚡ <i>Вопрос касается чего-то важного. Шар говорит серьёзно...</i>",
        "signoffs": [
            "⚡ <i>Я предупредила тебя. Остальное — твой выбор.</i>",
            "🕯️ <i>Держи свечу ближе к сердцу. Особенно сегодня.</i>",
            "🌑 <i>Не игнорируй знаки. Они посланы не просто так.</i>",
        ],
    },
    "joyful": {
        "prompt": "Твой тон сегодня тёплый, радостный и воодушевляющий. Ты видишь свет, возможности и удачу впереди. Говори с теплотой, надеждой и радостью.",
        "header_today": "✨ <i>Шар светится золотым... хорошие вести спешат к тебе...</i>",
        "header_week":  "🌟 <i>Звёзды складываются в улыбку... неделя несёт подарки...</i>",
        "header_ask":   "💫 <i>Шар радуется твоему вопросу... ответ полон надежды...</i>",
        "signoffs": [
            "🌹 <i>Иди смело. Звёзды сегодня за тебя.</i>",
            "✨ <i>Этот день — твой. Я в это верю.</i>",
            "💫 <i>Удача уже в пути. Только не закрывай ей дверь.</i>",
        ],
    },
}

SILENCE_MESSAGES = [
    "🌫️ <i>Туман слишком густой... <b>Звёзды молчат сегодня.</b> Попробуй снова позже.</i>",
    "🕯️ <i>Пламя свечи потухло в самый важный момент. <b>Шар не видит.</b> Вернись чуть позже...</i>",
    "🌑 <i>Тёмная луна закрыла все пути. <b>Сейчас не время для откровений.</b> Подожди немного.</i>",
    "🌊 <i>Воды судьбы слишком взволнованы... <b>Образы расплываются.</b> Спроси позже.</i>",
    "⚡ <i>Энергия рассеяна. <b>Нити судьбы спутались.</b> Дай шару отдохнуть и попробуй снова.</i>",
]

BASE_SYSTEM_PROMPT = """Ты — настоящая гадалка с даром ясновидения. Говоришь напрямую, смотришь человеку в глаза сквозь экран.

ГЛАВНОЕ ПРАВИЛО: никакой воды и общих слов. Каждое предложение — конкретное, личное, неожиданное.

Примеры ПЛОХИХ фраз (никогда так):
— "Впереди тебя ждут перемены" — слишком общо
— "Будь осторожна в делах" — ничего не значит
— "Удача улыбнётся тебе" — банально

Примеры ХОРОШИХ фраз (вот так надо):
— "Кто-то думает о тебе прямо сейчас. Не тот, кого ты ожидаешь."
— "Деньги придут не оттуда, откуда ждёшь. Обрати внимание на случайный разговор."
— "Старое сообщение, которое ты боялась отправить — отправь его сегодня."
— "Четверг — особый день, не планируй его слишком жёстко."

Правила стиля:
— Говори на "ты", коротко и точно — как будто шепчешь на ухо
— Касайся конкретных жизненных ситуаций: любовь, деньги, работа, здоровье, старые связи, неожиданные встречи
— Используй временны́е маркеры: "сегодня вечером", "в среду", "на этой неделе", "скоро"
— Называй конкретные действия: "позвони", "напиши", "не соглашайся", "скажи правду"
— Эмодзи органично, не больше 2-3 на весь текст: 🔮 💫 🌙 ❤️ 💰 🌊 🕯️ 🌹 ⚡
— 4-6 коротких предложений. Никакой воды.
— НЕ добавляй подпись или прощание в конце
— ТОЛЬКО русский язык
— НЕ используй списки, тире в начале строк, маркеры или bullet points. Пиши сплошным текстом — предложение за предложением."""

CARD_SYSTEM_PROMPT = """Ты — мастер таро с острым даром ясновидения. Создаёшь уникальные карты дня.

Придумай:
1. НАЗВАНИЕ — мистическое, оригинальное (не стандартные карты таро), с 1-2 эмодзи
2. ТОЛКОВАНИЕ — живое, конкретное, личное. Что именно происходит в жизни человека сегодня?

Формат СТРОГО:
НАЗВАНИЕ: [название с эмодзи]
ТОЛКОВАНИЕ: [3-4 предложения сплошным текстом, без тире в начале строк, без списков, конкретно и лично, на "ты"]

ТОЛЬКО русский язык. НЕ используй маркеры списков или тире в начале строк."""

RITUAL_SYSTEM_PROMPT = """Ты — мистический проводник. Даёшь один конкретный ритуал на день.

Ритуал должен быть:
— ВЫПОЛНИМЫМ прямо сегодня
— КОНКРЕТНЫМ действием

Формат:
Первое предложение — само действие (конкретно что делать).
Второе-третье — когда и как, плюс магический смысл.
Четвёртое — что это притянет или что отпустит.

Говори на "ты", тепло и таинственно. 3-4 предложения сплошным текстом. НЕ используй маркеры, тире в начале строк или списки. ТОЛЬКО русский язык."""


class AskState(StatesGroup):
    waiting_for_question = State()


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_TODAY)],
            [KeyboardButton(text=BTN_WEEK)],
            [KeyboardButton(text=BTN_CARD)],
            [KeyboardButton(text=BTN_RITUAL)],
            [KeyboardButton(text=BTN_ASK)],
        ],
        resize_keyboard=True,
        persistent=True,
        input_field_placeholder="Выбери или задай вопрос...",
    )


def pay_keyboard_unlimited() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👑 Безлимит на 30 дней — {PRICES['unlimited']} ⭐", callback_data="pay:unlimited")],
    ])


def pay_keyboard_question() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❓ Один вопрос — {PRICES['question']} ⭐", callback_data="pay:question")],
        [InlineKeyboardButton(text=f"👑 Безлимит на 30 дней — {PRICES['unlimited']} ⭐", callback_data="pay:unlimited")],
    ])


def get_moscow_date() -> str:
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")


def get_usage(user_id: int) -> dict:
    today = get_moscow_date()
    data = _user_usage.get(user_id, {})
    if data.get("date") != today:
        data = {"date": today, "today": 0, "card": 0, "questions": 0}
        _user_usage[user_id] = data
    return data


def has_unlimited(user_id: int) -> bool:
    expiry = _user_subscriptions.get(user_id)
    if expiry and datetime.now(MOSCOW_TZ) < expiry:
        return True
    _user_subscriptions.pop(user_id, None)
    return False


def grant_unlimited(user_id: int) -> datetime:
    expiry = datetime.now(MOSCOW_TZ) + timedelta(days=30)
    _user_subscriptions[user_id] = expiry
    return expiry


def pick_mood() -> dict:
    return random.choice(list(MOODS.values()))


def should_be_silent() -> bool:
    return random.random() < 0.20


def get_first_name(user) -> str:
    if user and user.first_name:
        return user.first_name
    return "странник"


def increment_counter() -> int:
    today = get_moscow_date()
    for k in list(_daily_counter.keys()):
        if k != today:
            del _daily_counter[k]
    _daily_counter[today] = _daily_counter.get(today, 0) + 1
    return _daily_counter[today]


def system_prompt_with_mood(mood: dict) -> str:
    return BASE_SYSTEM_PROMPT + f"\n\nТвоё настроение: {mood['prompt']}"


_CJK = re.compile(
    "[\u2E80-\u2EFF\u2F00-\u2FDF\u3000-\u303F\u3040-\u309F"
    "\u30A0-\u30FF\u3100-\u312F\u3200-\u32FF\u3300-\u33FF"
    "\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFE30-\uFE4F"
    "\U00020000-\U0002A6DF]+"
)

def clean_output(text: str) -> str:
    text = _CJK.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def animate_and_send(chat_id: int, feature: str) -> None:
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(3.0)


def fmt_prediction(sep: str, header: str, body: str, signoff: str, count: int) -> str:
    return (
        f"{sep}\n{header}\n{sep}\n\n"
        f"<i>{body}</i>\n\n"
        f"{signoff}\n\n"
        f"{SEP_END}\n"
        f"<i>Сегодня шар ответил уже <b>{count}</b> душам... 🔮</i>"
    )


async def send_invoice_for(chat_id: int, item: str) -> None:
    title, description, amount = INVOICE_META[item]
    await bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=item,
        provider_token="",  # пустой для Telegram Stars
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=amount)],
    )


async def get_prediction(period: str, mood: dict) -> str:
    prompt = (
        "Дай предсказание на СЕГОДНЯ. "
        "Укажи конкретное время (утром, к вечеру, сегодня ночью). "
        "Назови конкретное действие которое нужно или не нужно делать. "
        "Упомяни кого-то конкретного (старый друг, коллега, незнакомец, тот о ком думаешь). "
        "Не добавляй прощание в конце."
        if period == "today" else
        "Дай предсказание на БЛИЖАЙШУЮ НЕДЕЛЮ по дням. "
        "Назови конкретные дни недели (понедельник, среда, четверг, воскресенье). "
        "Для каждого ключевого дня — конкретное событие или действие. "
        "Не добавляй прощание в конце."
    )
    r = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt_with_mood(mood)},
            {"role": "user",   "content": prompt},
        ],
        temperature=1.0, max_tokens=350,
    )
    return clean_output(r.choices[0].message.content)


async def get_answer_to_question(question: str, mood: dict) -> str:
    r = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt_with_mood(mood)},
            {"role": "user",   "content": (
                f"Вопрос человека: «{question}»\n\n"
                "Ответь ПРЯМО на этот конкретный вопрос. "
                "Дай ответ как будто ты действительно видишь ситуацию. "
                "4-5 коротких предложений. Не добавляй прощание."
            )},
        ],
        temperature=1.0, max_tokens=350,
    )
    return clean_output(r.choices[0].message.content)


async def get_ritual_of_day() -> str:
    today = get_moscow_date()
    if today in _ritual_cache:
        return _ritual_cache[today]
    r = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": RITUAL_SYSTEM_PROMPT},
            {"role": "user",   "content": f"Уникальный магический ритуал на {today}. Конкретный, выполнимый."},
        ],
        temperature=1.1, max_tokens=250, seed=int(today.replace("-", "")) + 1,
    )
    text = clean_output(r.choices[0].message.content)
    _ritual_cache.clear()
    _ritual_cache[today] = text
    return text


async def get_card_of_day() -> str:
    today = get_moscow_date()
    if today in _card_cache:
        return _card_cache[today]
    r = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": CARD_SYSTEM_PROMPT},
            {"role": "user",   "content": f"Карта дня для {today}. Уникальная, отличается от вчерашней."},
        ],
        temperature=1.1, max_tokens=300, seed=int(today.replace("-", "")),
    )
    text = clean_output(r.choices[0].message.content)
    _card_cache.clear()
    _card_cache[today] = text
    return text


def parse_card(raw: str) -> tuple[str, str]:
    name, interpretation = "🎴 Карта дня", raw
    for line in raw.splitlines():
        if line.upper().startswith("НАЗВАНИЕ:"):
            name = line.split(":", 1)[1].strip()
        elif line.upper().startswith("ТОЛКОВАНИЕ:"):
            interpretation = line.split(":", 1)[1].strip()
    return name, interpretation


async def deliver_week(chat_id: int, name: str) -> None:
    mood = pick_mood()
    task = asyncio.create_task(get_prediction("week", mood))
    await animate_and_send(chat_id, "week")
    prediction = await task
    count = increment_counter()
    await bot.send_message(
        chat_id,
        f"<i>Я вижу тебя, <b>{name}</b>...</i>\n\n"
        + fmt_prediction(SEP_WEEK, mood["header_week"], prediction, random.choice(mood["signoffs"]), count)
    )


async def deliver_ritual(chat_id: int) -> None:
    task = asyncio.create_task(get_ritual_of_day())
    await animate_and_send(chat_id, "ritual")
    ritual = await task
    count = increment_counter()
    await bot.send_message(
        chat_id,
        f"{SEP_RITUAL}\n🕯️ <b>Ритуал дня избран для тебя...</b>\n{SEP_RITUAL}\n\n"
        f"<i>{ritual}</i>\n\n<i>✦ Выполни сегодня — и энергия дня будет на твоей стороне ✦</i>\n\n"
        f"{SEP_END}\n<i>Сегодня шар ответил уже <b>{count}</b> душам... 🔮</i>"
    )


async def deliver_question(chat_id: int, name: str, question: str) -> None:
    mood = pick_mood()
    task = asyncio.create_task(get_answer_to_question(question, mood))
    await animate_and_send(chat_id, "question")
    answer = await task
    count = increment_counter()
    await bot.send_message(
        chat_id,
        f"<i>Я слышу тебя, <b>{name}</b>...</i>\n\n"
        + fmt_prediction(SEP_ASK, mood["header_ask"], answer, random.choice(mood["signoffs"]), count)
    )


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    name = get_first_name(message.from_user)
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    await asyncio.sleep(2.0)
    await message.answer(
        f"🌑 <i>Тьма расступается...</i>\n"
        f"🔮 <i>Хрустальный шар пробуждается из тысячелетнего сна...</i>\n"
        f"👁 <i>Я вижу тебя, <b>{name}</b>. Ты пришёл не случайно.</i>\n\n"
        f"{SEP_TODAY}\n\n"
        f"<b>Судьба привела тебя сюда.</b>\n\n"
        f"<i>В глубине шара клубится туман.\n"
        f"Тысячи нитей твоей судьбы переплетаются прямо сейчас.\n"
        f"Выбери что хочешь узнать — шар ответит.</i>\n\n"
        f"{SEP_END}\n\n"
        f"<b>Бесплатно каждый день:</b>\n"
        f"<i>🔮 Предсказание на сегодня\n"
        f"🎴 Карта дня\n"
        f"👁 3 вопроса шару</i>\n\n"
        f"<b>За Звёзды ⭐:</b>\n"
        f"<i>🌙 Предсказание на неделю — 50 ⭐\n"
        f"🕯️ Ритуал дня — 30 ⭐\n"
        f"👑 Безлимит на 30 дней — 200 ⭐</i>",
        reply_markup=main_keyboard()
    )


@dp.message(F.text == BTN_TODAY)
async def prediction_today(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    chat_id = message.chat.id
    name = get_first_name(message.from_user)
    usage = get_usage(uid)

    if not has_unlimited(uid) and usage["today"] >= FREE_LIMITS["today"]:
        await message.answer(
            f"{SEP_PAY}\n"
            f"🔮 <b>Шар устал читать судьбы...</b>\n"
            f"{SEP_PAY}\n\n"
            f"<i>Ты уже получил бесплатное предсказание на сегодня.\n"
            f"Завтра шар снова откроется.\n\n"
            f"Или открой безлимит — и шар будет говорить без ограничений 30 дней.</i>",
            reply_markup=pay_keyboard_unlimited()
        )
        return

    if should_be_silent():
        await animate_and_send(chat_id, "today")
        await message.answer(random.choice(SILENCE_MESSAGES))
        return

    usage["today"] += 1
    mood = pick_mood()
    try:
        task = asyncio.create_task(get_prediction("today", mood))
        await animate_and_send(chat_id, "today")
        prediction = await task
        count = increment_counter()
        await message.answer(
            f"<i>Я вижу тебя, <b>{name}</b>...</i>\n\n"
            + fmt_prediction(SEP_TODAY, mood["header_today"], prediction, random.choice(mood["signoffs"]), count)
        )
    except Exception as e:
        usage["today"] -= 1
        logger.error(f"Groq error: {e}")
        await message.answer("🌑 <i>Тьма застилает видение... Попробуй снова.</i>")


@dp.message(F.text == BTN_WEEK)
async def prediction_week(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    chat_id = message.chat.id
    name = get_first_name(message.from_user)

    if has_unlimited(uid):
        if should_be_silent():
            await animate_and_send(chat_id, "week")
            await message.answer(random.choice(SILENCE_MESSAGES))
            return
        try:
            await deliver_week(chat_id, name)
        except Exception as e:
            logger.error(f"Groq error: {e}")
            await message.answer("🌑 <i>Туман скрывает дали... Попробуй снова.</i>")
        return

    await message.answer(
        f"{SEP_WEEK}\n"
        f"🌙 <b>Предсказание на неделю</b>\n"
        f"{SEP_WEEK}\n\n"
        f"<i>Шар видит семь дней вперёд — это требует особой силы.\n"
        f"Открой завесу судьбы за <b>{PRICES['week']} ⭐ Звёзд</b></i>"
    )
    await send_invoice_for(chat_id, "week")


@dp.message(F.text == BTN_CARD)
async def card_of_day(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    chat_id = message.chat.id
    usage = get_usage(uid)

    if not has_unlimited(uid) and usage["card"] >= FREE_LIMITS["card"]:
        await message.answer(
            f"{SEP_PAY}\n"
            f"🎴 <b>Карты закрыты до завтра...</b>\n"
            f"{SEP_PAY}\n\n"
            f"<i>Ты уже открыл свою карту дня.\n"
            f"Завтра придёт новая карта.\n\n"
            f"Или открой безлимит и получай карту в любое время.</i>",
            reply_markup=pay_keyboard_unlimited()
        )
        return

    usage["card"] += 1
    try:
        task = asyncio.create_task(get_card_of_day())
        await animate_and_send(chat_id, "card")
        raw = await task
        name_card, interpretation = parse_card(raw)
        count = increment_counter()
        await message.answer(
            f"{SEP_CARD}\n🎴 <b>{name_card}</b>\n{SEP_CARD}\n\n"
            f"<i>{interpretation}</i>\n\n"
            f"<i>✦ Карта меняется каждый день в полночь ✦</i>\n\n"
            f"{SEP_END}\n<i>Сегодня шар ответил уже <b>{count}</b> душам... 🔮</i>"
        )
    except Exception as e:
        usage["card"] -= 1
        logger.error(f"Card error: {e}")
        await message.answer("🌑 <i>Карты не открываются... Попробуй позже.</i>")


@dp.message(F.text == BTN_RITUAL)
async def ritual_of_day(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    chat_id = message.chat.id

    if has_unlimited(uid):
        try:
            await deliver_ritual(chat_id)
        except Exception as e:
            logger.error(f"Ritual error: {e}")
            await message.answer("🌑 <i>Ритуал не открылся... Попробуй позже.</i>")
        return

    await message.answer(
        f"{SEP_RITUAL}\n"
        f"🕯️ <b>Ритуал дня</b>\n"
        f"{SEP_RITUAL}\n\n"
        f"<i>Магический ритуал требует особой энергии шара.\n"
        f"Открой его за <b>{PRICES['ritual']} ⭐ Звёзд</b></i>"
    )
    await send_invoice_for(chat_id, "ritual")


@dp.message(F.text == BTN_ASK)
async def ask_prompt(message: Message, state: FSMContext):
    await state.set_state(AskState.waiting_for_question)
    uid = message.from_user.id
    name = get_first_name(message.from_user)
    usage = get_usage(uid)
    remaining = max(0, FREE_LIMITS["questions"] - usage["questions"])
    unlimited = has_unlimited(uid)

    if unlimited:
        footer = "<i>👑 У тебя безлимитный доступ</i>"
    elif remaining > 0:
        footer = f"<i>🆓 Осталось бесплатных вопросов сегодня: <b>{remaining}</b></i>"
    else:
        footer = f"<i>⭐ Бесплатные вопросы закончились — следующий за {PRICES['question']} ⭐</i>"

    await message.answer(
        f"{SEP_ASK}\n"
        f"👁 <b>Задай свой вопрос, {name}...</b>\n"
        f"{SEP_ASK}\n\n"
        f"<i>Шар слушает. Напиши то, что тревожит твою душу.\n"
        f"О любви, деньгах, работе, выборе — о чём угодно.</i>\n\n"
        f"{footer}"
    )


@dp.message(AskState.waiting_for_question)
async def handle_question(message: Message, state: FSMContext):
    text = message.text.strip() if message.text else ""

    if text in ALL_BTNS:
        await state.clear()
        await message.answer(
            "👁 <i>Ты нажал кнопку вместо вопроса.\n"
            "Если хочешь задать вопрос — напиши его словами.</i>"
        )
        return

    if not text:
        await message.answer("🌫️ <i>Пустота... Напиши вопрос словами.</i>")
        return

    await state.clear()
    uid = message.from_user.id
    chat_id = message.chat.id
    name = get_first_name(message.from_user)
    usage = get_usage(uid)

    if not has_unlimited(uid) and usage["questions"] >= FREE_LIMITS["questions"]:
        _pending_questions[uid] = text
        await message.answer(
            f"{SEP_PAY}\n"
            f"🔮 <b>Шар устал читать судьбы...</b>\n"
            f"{SEP_PAY}\n\n"
            f"<i>Бесплатные вопросы на сегодня исчерпаны.\n"
            f"Твой вопрос сохранён — оплати и получи ответ прямо сейчас.</i>",
            reply_markup=pay_keyboard_question()
        )
        return

    if should_be_silent():
        await animate_and_send(chat_id, "question")
        await message.answer(random.choice(SILENCE_MESSAGES))
        return

    usage["questions"] += 1
    try:
        await deliver_question(chat_id, name, text)
    except Exception as e:
        usage["questions"] -= 1
        logger.error(f"Groq error: {e}")
        await message.answer("🌑 <i>Видение прервалось... Попробуй снова.</i>")


@dp.callback_query(F.data.startswith("pay:"))
async def handle_pay_callback(callback: CallbackQuery):
    await callback.answer()
    item = callback.data.split(":")[1]
    await send_invoice_for(callback.message.chat.id, item)


@dp.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    uid = message.from_user.id
    chat_id = message.chat.id
    name = get_first_name(message.from_user)

    await message.answer(
        f"{SEP_PAY}\n"
        f"⭐ <b>Звёзды приняты. Шар пробуждается...</b>\n"
        f"{SEP_PAY}\n\n"
        f"<i>Древняя сила благодарит тебя за доверие, <b>{name}</b>.</i>"
    )

    if payload == "week":
        try:
            await deliver_week(chat_id, name)
        except Exception as e:
            logger.error(f"Groq error after payment: {e}")
            await bot.send_message(chat_id, "🌑 <i>Что-то пошло не так... Нажми кнопку ещё раз.</i>")

    elif payload == "ritual":
        try:
            await deliver_ritual(chat_id)
        except Exception as e:
            logger.error(f"Ritual error after payment: {e}")
            await bot.send_message(chat_id, "🌑 <i>Что-то пошло не так... Нажми кнопку ещё раз.</i>")

    elif payload == "question":
        question = _pending_questions.pop(uid, None)
        if question:
            try:
                await deliver_question(chat_id, name, question)
            except Exception as e:
                logger.error(f"Groq error after payment: {e}")
                await bot.send_message(chat_id, "🌑 <i>Что-то пошло не так... Задай вопрос снова.</i>")
        else:
            usage = get_usage(uid)
            usage["questions"] = max(0, usage["questions"] - 1)
            await bot.send_message(
                chat_id,
                "✨ <i>Оплата принята! Один вопрос добавлен.\n"
                "Нажми 👁 Задать вопрос шару и напиши его.</i>"
            )

    elif payload == "unlimited":
        expiry = grant_unlimited(uid)
        expiry_str = expiry.strftime("%d.%m.%Y")
        await bot.send_message(
            chat_id,
            f"{SEP_END}\n"
            f"👑 <b>Безлимитный доступ активирован!</b>\n"
            f"{SEP_END}\n\n"
            f"<i>До <b>{expiry_str}</b> шар будет открывать тебе все тайны без ограничений:\n\n"
            f"🔮 Предсказания на сегодня — без лимита\n"
            f"🌙 Предсказания на неделю — без лимита\n"
            f"🎴 Карта дня — без лимита\n"
            f"🕯️ Ритуал дня — без лимита\n"
            f"❓ Вопросы шару — без лимита\n\n"
            f"Судьба открыта тебе полностью.</i>\n\n"
            f"{SEP_END}"
        )


async def main():
    logger.info("🔮 Magic Ball Bot is awakening...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
