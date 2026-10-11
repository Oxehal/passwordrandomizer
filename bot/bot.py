import os
import io
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from google import genai
from google.genai import types as genai_types
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === НАСТРОЙКИ (лучше прописать в Environment Variables на Render) ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY")
ALLOWED_CHAT_ID    = int(os.getenv("TELEGRAM_CHAT_ID", "1266251966"))
SPREADSHEET_ID     = os.getenv("SPREADSHEET_ID", "")  # ID таблицы из её URL

# Инициализация клиентов
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def get_sheet():
    """Подключение к Google Sheets через Service Account (service_account.json)"""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    # Файл ключа от сервисного аккаунта Google Cloud
    creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).sheet1


@dp.message(CommandStart())
async def handle_start(message: types.Message):
    if message.chat.id != ALLOWED_CHAT_ID:
        return
    await message.answer(
        "👋 На связи! Надиктуй голосовым или напиши рейс в свободной форме.\n\n"
        "Пример:\n«ООО Восток, рейс 415 Казань, сумма 85 000, код ати 998877, 10 дней»"
    )


@dp.message(F.voice)
async def handle_voice(message: types.Message):
    if message.chat.id != ALLOWED_CHAT_ID:
        return

    status_msg = await message.answer("🎧 Скачиваю и слушаю голосовое...")

    # Скачивание аудио в память
    voice_file = await bot.get_file(message.voice.file_id)
    voice_buffer = io.BytesIO()
    await bot.download_file(voice_file.file_path, destination=voice_buffer)
    voice_bytes = voice_buffer.getvalue()

    prompt = (
        "Ты — парсер для логистики. Внимательно прослушай аудио на русском языке и верни JSON со свойствами: "
        "atiCode (строка/число, default ''), company (строка), orderInfo (строка), "
        "debtAmount (только число), contractDays (число, default 30), email (строка, default '')."
    )

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=voice_bytes, mime_type="audio/ogg")
            ],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        import json
        data = json.loads(response.text)

        if not data.get("company"):
            await status_msg.edit_text("⚠️ Не удалось распознать организацию. Надиктуй ещё раз.")
            return

        # Добавление в Google Sheets
        if SPREADSHEET_ID and os.path.exists("service_account.json"):
            sheet = get_sheet()
            next_row = len(sheet.get_all_values()) + 1
            ati_formula = f'=HYPERLINK("https://ati.su/firms/{data.get("atiCode")}/claims"; "🔍 Профиль АТИ")' if data.get("atiCode") else ""
            row_data = [
                data.get("atiCode", ""),
                data.get("company", ""),
                "",
                data.get("orderInfo", ""),
                float(data.get("debtAmount", 0)),
                "", "", "", "", "", "", "", "",
                int(data.get("contractDays", 30)),
                data.get("email", ""),
                ati_formula
            ]
            sheet.append_row(row_data, value_input_option="USER_ENTERED")

        text_reply = (
            f"✅ *Рейс успешно разобран!*\n\n"
            f"🏢 *Контрагент:* {data.get('company')}\n"
            f"🚛 *Рейс:* {data.get('orderInfo', 'не указан')}\n"
            f"💰 *Сумма:* {data.get('debtAmount')} руб.\n"
            f"⏱ *Срок:* {data.get('contractDays', 30)} дн.\n"
            f"🌐 *Код АТИ:* {data.get('atiCode', 'нет')}"
        )
        await status_msg.edit_text(text_reply, parse_mode="Markdown")

    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ошибка обработки: {str(e)}")


async def run_web_server():
    """Фиктивный веб-сервер, чтобы Render не считал сервис упавшим"""
    app = web.Application()
    app.router.add_get("/", lambda req: web.Response(text="Bot is running!"))
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(
        run_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
