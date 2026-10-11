import os
import io
import json
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from google import genai
from google.genai import types as genai_types

# Токены и переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_SHEET_WEBHOOK = "https://script.google.com/macros/s/AKfycbyFvhCTAWhZfTwuhZ_RLXNIy4p7XvHhryJVII-CLlWDWrDs2qHyAChCor3PgExSosL8/exec"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Клиент Gemini API
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT = (
    "Ты — логистический ассистент. Твоя задача — извлечь данные о рейсе или дебиторской задолженности из сообщения водителя/диспетчера.\n"
    "Верни ТОЛЬКО валидный JSON со следующими ключами:\n"
    "- company: Название контрагента/заказчика (например: \"ООО Восток\")\n"
    "- orderInfo: Описание рейса, маршрут или номер заявки (например: \"рейс 415 Казань - Москва\")\n"
    "- debtAmount: Сумма долга или ставка чистым числом без пробелов и валюты (например: 85000)\n"
    "- contractDays: Срок оплаты в днях числом (если не сказано, поставь 30)\n"
    "- atiCode: Код АТИ фирмы, если упомянут (число или строка), иначе null\n"
    "- email: Почта, если упомянута, иначе null\n\n"
    "Формат строго JSON, без markdown разметки ```json:\n"
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
    """Отправка JSON данных в Google Apps Script Webhook."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GOOGLE_SHEET_WEBHOOK, json=data, timeout=10) as resp:
                return resp.status == 200
    except Exception as exc:
        print(f"Ошибка запроса к Google Таблице: {exc}")
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
            # Скачивание голосовой записи в оперативную память
            file_info = await bot.get_file(message.voice.file_id)
            voice_file = io.BytesIO()
            await bot.download_file(file_info.file_path, destination=voice_file)
            voice_bytes = voice_file.getvalue()

            # Вызов Gemini в отдельном потоке (без блокировки цикла событий)
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

        # Разбор результата
        text_json = response.text.strip()
        data = json.loads(text_json)

        # Запись в таблицу через вебхук
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

async def main():
    print("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
