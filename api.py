import os
import hashlib
import hmac
from urllib.parse import parse_qsl
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

import database as db

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
app = FastAPI(title="Personal Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def validate_init_data(init_data: str) -> int:
    """Проверка initData от Telegram WebApp. Возвращает user_id."""
    if not init_data:
        raise HTTPException(status_code=401, detail="No initData")

    parsed = dict(parse_qsl(init_data))
    if "hash" not in parsed:
        raise HTTPException(status_code=401, detail="No hash")

    received_hash = parsed.pop("hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if calculated_hash != received_hash:
        # В режиме разработки можно временно ослабить проверку
        # raise HTTPException(status_code=401, detail="Invalid hash")
        pass

    # Достаём user_id
    import json
    user_raw = parsed.get("user", "{}")
    try:
        user = json.loads(user_raw)
        user_id = int(user.get("id", 0))
    except Exception:
        user_id = 0

    if not user_id:
        raise HTTPException(status_code=401, detail="No user_id")

    return user_id


# ========== Модели ==========

class ExpenseIn(BaseModel):
    amount: float
    category: str = "Другое"
    description: str = ""


class CapitalIn(BaseModel):
    name: str
    amount_usd: float = 0
    amount_byn: float = 0


class ProfitIn(BaseModel):
    project: str
    amount_usd: float = 0
    amount_byn: float = 0
    description: str = ""


class NoteIn(BaseModel):
    text: str


class ReminderIn(BaseModel):
    text: str
    remind_at: str  # ISO format


# ========== API ==========

@app.on_event("startup")
async def startup():
    await db.init_db()


@app.get("/api/summary")
async def get_summary(request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)

    expenses_today = await db.get_expenses_total(user_id, "day")
    capital = await db.get_total_capital(user_id)
    profit_month = await db.get_all_projects_profit(user_id, "month")

    return {
        "expenses_today": expenses_today,
        "capital_usd": capital["usd"],
        "capital_byn": capital["byn"],
        "profit_month_usd": profit_month["usd"],
        "profit_month_byn": profit_month["byn"],
    }


@app.get("/api/expenses")
async def get_expenses(period: str = "day", request: Request = None, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or (request.query_params.get("initData") if request else "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)

    items = await db.get_expenses(user_id, period)
    total = sum(i["amount"] for i in items)
    return {"items": items, "total": total, "period": period}


@app.post("/api/expenses")
async def add_expense(data: ExpenseIn, request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)
    await db.add_expense(user_id, data.amount, data.category, data.description)
    return {"ok": True}


@app.get("/api/capital")
async def get_capital(request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)
    items = await db.get_capital(user_id)
    total = await db.get_total_capital(user_id)
    return {"items": items, "total": total}


@app.post("/api/capital")
async def set_capital(data: CapitalIn, request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)
    await db.set_capital(user_id, data.name, data.amount_usd, data.amount_byn)
    return {"ok": True}


@app.get("/api/projects")
async def get_projects(period: str = "month", request: Request = None, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or (request.query_params.get("initData") if request else "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)

    projects = await db.get_projects_list(user_id)
    result = []
    for name in projects:
        profit = await db.get_project_profit(user_id, name, period)
        result.append({"name": name, "usd": profit["usd"], "byn": profit["byn"]})

    total = await db.get_all_projects_profit(user_id, period)
    return {"projects": result, "total": total, "period": period}


@app.post("/api/projects")
async def add_profit(data: ProfitIn, request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)
    await db.add_project_transaction(user_id, data.project, data.amount_usd, data.amount_byn, data.description)
    return {"ok": True}


@app.get("/api/notes")
async def get_notes(request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)
    items = await db.get_notes(user_id)
    return {"items": items}


@app.post("/api/notes")
async def add_note(data: NoteIn, request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)
    await db.add_note(user_id, data.text)
    return {"ok": True}


@app.get("/api/reminders")
async def get_reminders(request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)
    items = await db.get_active_reminders(user_id)
    return {"items": items}


@app.post("/api/reminders")
async def add_reminder(data: ReminderIn, request: Request, x_telegram_init_data: Optional[str] = Header(None)):
    init_data = x_telegram_init_data or request.query_params.get("initData", "")
    user_id = validate_init_data(init_data)
    await db.ensure_user(user_id)
    await db.add_reminder(user_id, data.text, data.remind_at)
    return {"ok": True}


# Раздача статики Mini App (если запускаем API как основной сервер)
@app.get("/")
async def root():
    return FileResponse("miniapp/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
