import os
import io
import json
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from google import genai
from google.genai import types as genai_types

# Токены и настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_SHEET_WEBHOOK = "https://script.google.com/macros/s/AKfycbyFvhCTAWhZfTwuhZ_RLXNIy4p7XvHhryJVII-CLlWDWrDs2qHyAChCor3PgExSosL8/exec"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация Gemini
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT = """
Ты — логистический ассистент. Твоя задача — извлечь данные о рейсе или дебиторской задолженности из сообщения водителя/диспетчера.
Верни ТОЛЬКО валидный JSON со следующими ключами:
- company: Название контрагента/заказчика (например: "ООО Восток")
- orderInfo: Описание рейса, маршрут или номер заявки (например: "рейс 415 Казань - Москва")
- debtAmount: Сумма долга или ставка чистым числом без пробелов и валюты (например: 85000)
- contractDays: Срок оплаты в днях числом (если не сказано, поставь 30)
- atiCode: Код АТИ фирмы, если упомянут (число или строка), иначе null
- email: Почта, если упомянута, иначе null

Формат строго JSON, без markdown разметки ```json:
{
  "company": "...",
  "orderInfo": "...",
  "debtAmount": 0,
  "contractDays": 30,
  "atiCode": null,
  "email": null
}
"""

async def send_to_sheets(data: dict):
    """Отправка данных в Google Таблицу через вебхук"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GOOGLE_SHEET_WEBHOOK, json=data, timeout=10) as resp:
                return resp.status == 200
    except Exception as e:
        print(f"Ошибка отправки в таблицу: {e}")
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
            # Скачиваем голосовое сообщение в память
            file_info = await bot.get_file(message.voice.file_id)
            voice_file = io.BytesIO()
            await bot.download_file(file_info.file_path, destination=voice_file)
            voice_bytes = voice_file.getvalue()

            # Запрос к Gemini (через to_thread для ускорения)
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

        text_json = response.text.strip()
        data = json.loads(text_json)

        # Отправляем данные в Google Таблицу
        sheet_success = await send_to_sheets(data)

        # Красивый вывод для Telegram
        reply = (
            "✅ **Рейс успешно разобран!**\n\n"
            f"🏢 **Контрагент:** {data.get('company', '—')}\n"
            f"🚛 **Рейс:** {data.get('orderInfo', '—')}\n"
            f"💰 **Сумма:** {data.get('debtAmount', 0)} руб.\n"
            f"⏱ **Срок:** {data.get('contractDays', 30)} дн.\n"
            f"🌐 **Код АТИ:** {data.get('atiCode') or '—'}\n\n"
        )
        
        if sheet_success:
            reply +=
