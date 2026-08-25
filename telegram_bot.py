import os
import time
import json
import urllib.request
import urllib.parse

import monitor

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = str(os.environ["TELEGRAM_CHAT_ID"])


def get_updates(offset):
    params = urllib.parse.urlencode({
        "offset": offset,
        "timeout": 25,
        "allowed_updates": json.dumps(["message"]),
    })

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?{params}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "btc-telegram-monitor-realtime/1.0"}
    )

    with urllib.request.urlopen(req, timeout=35) as response:
        data = json.loads(response.read().decode("utf-8"))

    return data.get("result", [])


def main():
    state = monitor.load_state()
    history = monitor.load_history()

    offset = int(state.get("update_offset", 0))

    print("Realtime Telegram Bot started", flush=True)

    while True:
        try:
            updates = get_updates(offset)

            for update in updates:
                offset = int(update["update_id"]) + 1

                message = update.get("message") or {}
                chat = message.get("chat") or {}

                chat_id = str(chat.get("id", ""))
                text = message.get("text", "")

                if not text:
                    continue

                if chat_id != CHAT_ID:
                    continue

                print(
                    f"Received command: {text}",
                    flush=True
                )

                history = monitor.handle_command(
                    text,
                    state,
                    history
                )

                state["update_offset"] = offset

                monitor.save_state(state)
                monitor.save_history(history)

        except Exception as e:
            print(
                f"BOT ERROR: {e}",
                flush=True
            )

            time.sleep(5)


if __name__ == "__main__":
    main()
