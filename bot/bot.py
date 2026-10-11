import os
import io
import json
import asyncio
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from google import genai
from google.genai import types as genai_types

# Токены и вебхук
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_SHEET_WEBHOOK = "https://script.google.com/macros/s/AKfycbyFvhCTAWhZfTwuhZ_RLXNIy4p7XvHhryJVII-CLlWDWrDs2qHyAChCor3PgExSosL8/exec"
PORT = int(os.environ.get("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT = (
    "Ты — логистический ассистент. Твоя задача — извлечь данные о рейсе или задолженности из сообщения.\n"
    "Верни ТОЛЬКО валидный JSON со следующими ключами:\n"
    "- company: Название контрагента/заказчика (например: \"ООО Восток\")\n"
    "- orderInfo: Описание рейса, маршрут или номер заявки (например: \"рейс 415 Казань - Москва\")\n"
    "- debtAmount: Сумма чистым числом без пробелов и валюты (например: 85000)\n"
    "- contractDays: Срок оплаты в днях числом (если не сказано, поставь 30)\n"
    "- atiCode: Код АТИ фирмы, если упомянут, иначе null\n"
    "- email: Почта, если упомянута, иначе null\n\n"
    "Формат строго JSON:\n"
    "{\n"
    "  \"company\": \"...\",\n"
    "  \"orderInfo\": \"...\",\n"
    "  \"debtAmount\": 0,\n"
    "  \"contractDays\": 30,\n"
    "  \"atiCode\": null,\n"
    "  \"email\": null\n"
    "}"
)

async def send_to_sheets(data: dict) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GOOGLE_SHEET_WEBHOOK, json=data, timeout=10) as resp:
                return resp.status == 200
    except Exception as exc:
        print(f"Ошибка запроса к таблице: {exc}")
        return False

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 На связи! Надиктуй голосовым или напиши рейс в свободной форме.\n\n"
        "Пример:\n"
        "«ООО Восток, рейс 415 Казань, сумма 85 000, код ати 998877, 10 дней»"
    )

@dp.message(F.voice | F.text)
async def handle_payload(message: types.Message):
    status_msg = await message.answer("🎧 Обрабатываю данные...")
    try:
        if message.voice:
            file_info = await bot.get_file(message.voice.file_id)
            voice_file = io.BytesIO()
            await bot.download_file(file_info.file_path, destination=voice_file)
            voice_bytes = voice_file.getvalue()

            response = await asyncio.to_thread(
                gemini_client.models.generate_content,
                model="gemini-3.8-flash",
                contents=[
                    PROMPT,
                    genai_types.Part.from_bytes(data=voice_bytes, mime_type="audio/ogg")
                ],
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
        else:
            response = await asyncio.to_thread(
                gemini_client.models.generate_content,
                model="gemini-3.8-flash",
                contents=[PROMPT, message.text],
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )

        data = json.loads(response.text.strip())
        sheet_success = await send_to_sheets(data)

        company = data.get("company", "—")
        order_info = data.get("orderInfo", "—")
        debt_amount = data.get("debtAmount", 0)
        contract_days = data.get("contractDays", 30)
        ati_code = data.get("atiCode") or "—"

        status_text = (
            "📊 _Данные автоматически занесены в Google Таблицу!_"
            if sheet_success
            else "⚠️ _Не удалось сохранить в таблицу, проверьте вебхук._"
        )

        reply = (
            "✅ *Рейс успешно разобран!*\n\n"
            f"🏢 *Контрагент:* {company}\n"
            f"🚛 *Рейс:* {order_info}\n"
            f"💰 *Сумма:* {debt_amount} руб.\n"
            f"⏱ *Срок:* {contract_days} дн.\n"
            f"🌐 *Код АТИ:* {ati_code}\n\n"
            f"{status_text}"
        )
        await status_msg.edit_text(reply, parse_mode="Markdown")

    except Exception as exc:
        await status_msg.edit_text(f"⚠️ Ошибка обработки: {exc}")

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def main():
    # Удаляем зависшие вебхуки Telegram перед запуском
    await bot.delete_webhook(drop_pending_updates=True)

    # Запуск фонового веб-сервера для Render
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Веб-сервер запущен на порту {PORT}")

    # Запуск поллинга aiogram
    print("Бот слушает сообщения...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
