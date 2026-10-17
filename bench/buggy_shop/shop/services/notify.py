import json
import urllib.request

from shop.config import WEBHOOK_URL


def send_order_webhook(order: dict) -> int:
    body = json.dumps(order).encode()
    req = urllib.request.Request(
        WEBHOOK_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status
