import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, FileResponse
from telegram import Bot, Update

from agent import answer_question

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"].rstrip("/")  # e.g. https://your-app.onrender.com
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "run.jsonl")
LOG_URL = f"{PUBLIC_BASE_URL}/logs/run.jsonl"

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
open(LOG_PATH, "a").close()  # ensure file exists

app = FastAPI()
bot = Bot(token=BOT_TOKEN)

# very small in-memory per-chat conversation store (fine for grading window)
CONVERSATIONS: dict[int, list[dict]] = {}


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/logs/run.jsonl")
def get_log():
    return FileResponse(LOG_PATH, media_type="application/jsonl")


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot)

    if not update.message or not update.message.text:
        return {"ok": True}

    chat_id = update.message.chat_id
    text = update.message.text

    history = CONVERSATIONS.setdefault(chat_id, [])
    history.append({"role": "user", "content": text})

    try:
        answer = answer_question(history, LOG_PATH)
    except Exception as e:  # noqa: BLE001
        answer = f"error: {e}"

    reply_obj = {"answer": answer, "log_url": LOG_URL}
    reply_text = json.dumps(reply_obj)

    history.append({"role": "assistant", "content": reply_text})
    # keep history bounded
    CONVERSATIONS[chat_id] = history[-20:]

    await bot.send_message(chat_id=chat_id, text=reply_text)
    return {"ok": True}
