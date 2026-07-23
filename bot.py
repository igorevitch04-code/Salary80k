import asyncio
import re
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from dotenv import load_dotenv
import os

import database as db

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
# Укажи сюда URL своего Mini App (после деплоя или через ngrok)
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://your-miniapp-url.com")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()


# ========== ПАРСИНГ СООБЩЕНИЙ ==========

def parse_expense(text: str) -> dict | None:
    """Парсит расходы: 'потратил 45 на продукты', 'стрижка 200', 'такси 18.5'"""
    text = text.lower().strip()

    # паттерны
    patterns = [
        r"(?:потратил|трата|расход|купил)?\s*(\d+[.,]?\d*)\s*(?:byn|руб|р|бел)?\s*(?:на\s+)?(.+)",
        r"(.+?)\s+(\d+[.,]?\d*)\s*(?:byn|руб|р)?$",
    ]

    for pat in patterns:
        m = re.search(pat, text)
        if m:
            groups = m.groups()
            if groups[0].replace(",", ".").replace(".", "", 1).isdigit():
                amount = float(groups[0].replace(",", "."))
                desc = groups[1].strip() if len(groups) > 1 else "Другое"
            else:
                desc = groups[0].strip()
                amount = float(groups[1].replace(",", "."))
            # простая категоризация
            category = "Другое"
            cat_map = {
                "еда": ["продукт", "еда", "обед", "ужин", "завтрак", "кофе", "ресторан", "магазин"],
                "транспорт": ["такси", "бензин", "метро", "автобус", "транспорт", "яндекс"],
                "здоровье": ["стрижк", "аптека", "врач", "медиц", "лекар"],
                "подписки": ["подписк", "chatgpt", "spotify", "netflix", "сервис"],
            }
            for cat, keywords in cat_map.items():
                if any(k in desc.lower() for k in keywords):
                    category = cat.capitalize()
                    break
            return {"amount": amount, "category": category, "description": desc}
    return None


def parse_profit(text: str) -> dict | None:
    """Парсит профит: 'крипта +150$', 'трафик +85$', 'крипта +420 byn'"""
    text = text.lower().strip()
    m = re.search(r"([а-яa-z0-9_\-]+)\s*\+?\s*(\d+[.,]?\d*)\s*(\$|usd|byn|руб)?", text)
    if m:
        project = m.group(1).strip()
        amount = float(m.group(2).replace(",", "."))
        currency = (m.group(3) or "$").lower()
        if currency in ("byn", "руб"):
            return {"project": project, "amount_usd": 0, "amount_byn": amount}
        else:
            return {"project": project, "amount_usd": amount, "amount_byn": 0}
    return None


def parse_capital(text: str) -> dict | None:
    """Парсит капитал: 'капитал крипта 4500$', 'капитал наличные 3200$'"""
    text = text.lower().strip()
    m = re.search(r"капитал\s+([а-яa-z0-9_\-\s]+?)\s+(\d+[.,]?\d*)\s*(\$|usd|byn|руб)?", text)
    if m:
        name = m.group(1).strip()
        amount = float(m.group(2).replace(",", "."))
        currency = (m.group(3) or "$").lower()
        if currency in ("byn", "руб"):
            return {"name": name, "amount_usd": 0, "amount_byn": amount}
        else:
            return {"name": name, "amount_usd": amount, "amount_byn": 0}
    return None


def parse_note(text: str) -> str | None:
    text_l = text.lower().strip()
    if text_l.startswith("заметка:") or text_l.startswith("идея:") or text_l.startswith("note:"):
        return text.split(":", 1)[1].strip()
    return None


def parse_reminder(text: str) -> dict | None:
    """Простой парсер напоминаний"""
    text_l = text.lower().strip()
    if not text_l.startswith("напомни"):
        return None

    # напомни завтра в 11 ...
    m = re.search(r"напомни\s+(завтра|послезавтра)?\s*(?:в\s+)?(\d{1,2})(?::(\d{2}))?\s+(.+)", text_l)
    if m:
        day_word, hour, minute, remind_text = m.groups()
        minute = int(minute) if minute else 0
        hour = int(hour)
        now = datetime.now()
        if day_word == "завтра":
            target = now + timedelta(days=1)
        elif day_word == "послезавтра":
            target = now + timedelta(days=2)
        else:
            target = now
        target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target < now:
            target += timedelta(days=1)
        return {"text": remind_text.strip(), "remind_at": target.isoformat()}

    # напомни через 2 часа
    m = re.search(r"напомни\s+через\s+(\d+)\s*(час|часа|часов|мин|минут)\s+(.+)", text_l)
    if m:
        num, unit, remind_text = m.groups()
        num = int(num)
        now = datetime.now()
        if "час" in unit:
            target = now + timedelta(hours=num)
        else:
            target = now + timedelta(minutes=num)
        return {"text": remind_text.strip(), "remind_at": target.isoformat()}

    return None


# ========== ХЕНДЛЕРЫ ==========

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await db.ensure_user(message.from_user.id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Открыть Ассистента",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )]
    ])

    await message.answer(
        "Привет! Я твой личный ассистент.\n\n"
        "Можешь писать мне сообщения:\n"
        "• <code>потратил 45 на продукты</code>\n"
        "• <code>крипта +150$</code>\n"
        "• <code>капитал крипта 4500$</code>\n"
        "• <code>заметка: проверить поставщика</code>\n"
        "• <code>напомни завтра в 11 созвон</code>\n\n"
        "Или открой Mini App для полного обзора:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("app"))
async def cmd_app(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Открыть Ассистента",
            web_app=WebAppInfo(url=MINI_APP_URL)
        )]
    ])
    await message.answer("Открывай:", reply_markup=kb)


@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    await db.ensure_user(user_id)
    text = message.text.strip()

    # 1. Расход
    expense = parse_expense(text)
    if expense:
        await db.add_expense(user_id, expense["amount"], expense["category"], expense["description"])
        await message.answer(
            f"✅ Расход записан\n"
            f"Сумма: <b>{expense['amount']:.2f} BYN</b>\n"
            f"Категория: {expense['category']}\n"
            f"Описание: {expense['description']}",
            parse_mode=ParseMode.HTML
        )
        return

    # 2. Профит по проекту
    profit = parse_profit(text)
    if profit:
        await db.add_project_transaction(
            user_id,
            profit["project"],
            profit["amount_usd"],
            profit["amount_byn"]
        )
        curr = f"{profit['amount_usd']:.2f}$" if profit["amount_usd"] else f"{profit['amount_byn']:.2f} BYN"
        await message.answer(
            f"✅ Профит записан\n"
            f"Проект: <b>{profit['project']}</b>\n"
            f"Сумма: <b>+{curr}</b>",
            parse_mode=ParseMode.HTML
        )
        return

    # 3. Капитал
    capital = parse_capital(text)
    if capital:
        await db.set_capital(
            user_id,
            capital["name"],
            capital["amount_usd"],
            capital["amount_byn"]
        )
        curr = f"{capital['amount_usd']:.2f}$" if capital["amount_usd"] else f"{capital['amount_byn']:.2f} BYN"
        await message.answer(
            f"✅ Капитал обновлён\n"
            f"<b>{capital['name']}</b>: {curr}",
            parse_mode=ParseMode.HTML
        )
        return

    # 4. Заметка
    note = parse_note(text)
    if note:
        await db.add_note(user_id, note)
        await message.answer(f"✅ Заметка сохранена:\n<i>{note}</i>", parse_mode=ParseMode.HTML)
        return

    # 5. Напоминание
    reminder = parse_reminder(text)
    if reminder:
        await db.add_reminder(user_id, reminder["text"], reminder["remind_at"])
        dt = datetime.fromisoformat(reminder["remind_at"]).strftime("%d.%m %H:%M")
        await message.answer(
            f"✅ Напоминание поставлено\n"
            f"Когда: <b>{dt}</b>\n"
            f"Текст: {reminder['text']}",
            parse_mode=ParseMode.HTML
        )
        return

    # Если ничего не распознали
    await message.answer(
        "Не понял сообщение.\n\n"
        "Примеры:\n"
        "• потратил 45 на продукты\n"
        "• крипта +150$\n"
        "• капитал крипта 4500$\n"
        "• заметка: текст\n"
        "• напомни завтра в 11 созвон"
    )


async def main():
    await db.init_db()
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
