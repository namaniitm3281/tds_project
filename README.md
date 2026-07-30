# tds-data-agent-bot

A Telegram bot backed by a Claude-powered data-analyst agent. It receives a
plain-text data-analysis question, fetches/analyzes real public data with a
sandboxed Python tool, and replies with exactly one JSON object:

```json
{"answer": <value>, "log_url": "https://<host>/logs/run.jsonl"}
```

## How it works
- `app.py` — FastAPI service. `/webhook` receives Telegram updates,
  `/logs/run.jsonl` serves the running audit log (public, wget-able).
- `agent.py` — a small ReAct loop: Claude gets a `run_python` tool
  (subprocess, pandas/numpy/requests/openpyxl, internet access) and a
  `final_answer` tool. It fetches data, computes, and submits the answer
  in the exact shape the question asked for.
- Every model turn and tool call/result is appended to `logs/run.jsonl`.
- Per-chat conversation history is kept in memory so multi-turn questions
  work (the agent answers the latest message with prior context).

## 1. Local setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, PUBLIC_BASE_URL
```

### Create the bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot`.
2. Pick a name and a username ending in `bot`.
3. Copy the token into `TELEGRAM_BOT_TOKEN`.

## 2. Deploy (Render.com, free tier)
1. Push this repo to GitHub (public).
2. On Render: New → Blueprint → point at this repo (`render.yaml` is
   already set up with a persistent disk for `logs/`).
3. Set the env vars `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, and
   `PUBLIC_BASE_URL` (your Render service URL, e.g.
   `https://tds-data-agent-bot.onrender.com`) in the Render dashboard.
4. Deploy. Once live, register the webhook once:
   ```bash
   TELEGRAM_BOT_TOKEN=... PUBLIC_BASE_URL=https://your-app.onrender.com \
     python3 set_webhook.py
   ```
5. Verify: `wget https://your-app.onrender.com/logs/run.jsonl` should
   return 200 (empty file is fine before first run).

Any other host works too (Railway, Fly.io, a VPS) — just make sure
`logs/run.jsonl` persists across restarts and stays reachable at
`PUBLIC_BASE_URL/logs/run.jsonl`, and keep the service always-on for
grading (free-tier services that sleep on idle may need a keep-alive
ping or a paid "always on" tier).

## 3. Test locally against the grading harness
```bash
git clone https://github.com/Jivraj-18/tds-p1-t2-2026-telegram-bot
# follow its README, point it at your bot's @username, add sample
# questions to evals/questions.json
```

## 4. Registration line
```
https://github.com/<you>/tds-data-agent-bot, your_bot_username_bot
```
