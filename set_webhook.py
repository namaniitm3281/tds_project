"""Run once after deploying: python3 set_webhook.py
Requires env vars TELEGRAM_BOT_TOKEN and PUBLIC_BASE_URL to be set.
"""
import os
import requests

token = os.environ["TELEGRAM_BOT_TOKEN"]
base_url = os.environ["PUBLIC_BASE_URL"].rstrip("/")

resp = requests.post(
    f"https://api.telegram.org/bot{token}/setWebhook",
    data={"url": f"{base_url}/webhook"},
)
print(resp.status_code, resp.text)
