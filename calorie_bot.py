import os
import base64
import json
import logging
from datetime import datetime
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==============================
# ВСТАВЬ СВОИ ТОКЕНЫ СЮДА:
# ==============================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# ==============================

DAILY_LIMIT = 1950
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

diary = {}

def get_today():
    return datetime.now().strftime("%Y-%m-%d")

def get_user_diary(user_id):
    today = get_today()
    if user_id not in diary or diary[user_id]["date"] != today:
        diary[user_id] = {"date": today, "total": 0, "items": []}
    return diary[user_id]

async def analyze_food_photo(image_bytes: bytes) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = """Ты диетолог-ассистент. Пользователь прислал фото еды.
Определи блюдо и оцени калорийность порции на фото.
Отвечай ТОЛЬКО в JSON формате без лишнего текста и без markdown:
{"dish":"название блюда","weight_g":300,"calories":450,"protein_g":25,"fat_g":15,"carbs_g":40,"comment":"короткий комментарий на русском"}
Если на фото не еда верни: {"error":"На фото не еда"}"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}}
            ]
        }]
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload)
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой помощник по калориям.\n\n"
        "📸 Пришли фото еды — я посчитаю калории!\n\n"
        "Команды:\n"
        "/today — дневник за сегодня\n"
        "/reset — сбросить дневник\n"
        f"\nТвоя цель: {DAILY_LIMIT} ккал/день 🎯"
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    d = get_user_diary(user_id)
    if not d["items"]:
        await update.message.reply_text("📋 Сегодня ты ещё ничего не записал. Пришли фото еды!")
        return
    text = "📊 *Дневник за сегодня:*\n\n"
    for i, item in enumerate(d["items"], 1):
        text += f"{i}. {item['dish']} — {item['calories']} ккал\n"
    remaining = DAILY_LIMIT - d["total"]
    status = "✅" if remaining > 0 else "⚠️"
    text += f"\n*Итого:* {d['total']} / {DAILY_LIMIT} ккал"
    text += f"\n{status} *Остаток:* {max(0, remaining)} ккал"
    await update.message.reply_text(text, parse_mode="Markdown")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    diary[user_id] = {"date": get_today(), "total": 0, "items": []}
    await update.message.reply_text("🔄 Дневник сброшен!")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("🔍 Анализирую фото...")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(file.file_path)
        image_bytes = resp.content
    try:
        result = await analyze_food_photo(image_bytes)
        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
            return
        d = get_user_diary(user_id)
        d["items"].append({"dish": result["dish"], "calories": result["calories"]})
        d["total"] += result["calories"]
        remaining = DAILY_LIMIT - d["total"]
        status = "✅" if remaining > 0 else "⚠️ Превышение!"
        text = (
            f"🍽 *{result['dish']}*\n\n"
            f"⚡ Калории: *{result['calories']} ккал*\n"
            f"🥩 Белки: {result['protein_g']} г\n"
            f"🧈 Жиры: {result['fat_g']} г\n"
            f"🍞 Углеводы: {result['carbs_g']} г\n"
            f"📦 Вес порции: ~{result['weight_g']} г\n\n"
            f"💬 {result['comment']}\n\n"
            f"📊 За сегодня: *{d['total']} / {DAILY_LIMIT} ккал*\n"
            f"{status} Остаток: {max(0, remaining)} ккал"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("😔 Не смог определить. Попробуй другое фото.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Пришли фото еды — и я посчитаю калории!\n\n"
        "Команды:\n/today — дневник\n/reset — сброс"
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
