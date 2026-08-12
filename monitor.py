import os
import json
import urllib.request
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_btc():
    urls = [
        "https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT",
        "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT",
    ]

    last_error = None

    for url in urls:
        try:
            data = get_json(url)
            price = float(data["lastPrice"])
            change = float(data["priceChangePercent"])
            return price, change
        except Exception as e:
            last_error = e

    raise last_error


def get_fear_greed():
    data = get_json("https://api.alternative.me/fng/?limit=1")
    item = data["data"][0]

    value = int(item["value"])
    classification = item["value_classification"]

    cn = {
        "Extreme Fear": "极度恐惧",
        "Fear": "恐惧",
        "Neutral": "中性",
        "Greed": "贪婪",
        "Extreme Greed": "极度贪婪",
    }

    return value, cn.get(classification, classification)


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload)

    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


def main():
    btc_price, btc_change = get_btc()
    fng_value, fng_text = get_fear_greed()

    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")

    change_icon = "🟢" if btc_change >= 0 else "🔴"
    change_sign = "+" if btc_change >= 0 else ""

    message = (
        "📊 BTC 市场监控\n\n"
        f"₿ BTC：${btc_price:,.0f}\n"
        f"{change_icon} 24H：{change_sign}{btc_change:.2f}%\n\n"
        f"😨 恐惧贪婪：{fng_value}/100（{fng_text}）\n\n"
        f"🕒 {now} 北京时间\n"
        "📡 数据源：Binance / Alternative.me"
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
