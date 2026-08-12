import os
import json
import re
import urllib.request
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
from html.parser import HTMLParser


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def get_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9"
        }
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def get_json(url):
    return json.loads(get_text(url))


# =========================
# BTC 价格
# =========================
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


# =========================
# 恐惧贪婪指数
# =========================
def get_fear_greed():

    data = get_json(
        "https://api.alternative.me/fng/?limit=1"
    )

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

    return value, cn.get(
        classification,
        classification
    )


# =========================
# HTML 表格解析
# =========================
class TableParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.rows = []

        self.current_row = None
        self.current_cell = None
        self.in_cell = False

    def handle_starttag(self, tag, attrs):

        if tag == "tr":
            self.current_row = []

        elif tag in ("td", "th"):

            self.current_cell = []
            self.in_cell = True

    def handle_data(self, data):

        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag):

        if tag in ("td", "th"):

            if self.current_row is not None:

                text = " ".join(
                    "".join(self.current_cell).split()
                )

                self.current_row.append(text)

            self.current_cell = None
            self.in_cell = False

        elif tag == "tr":

            if self.current_row:
                self.rows.append(self.current_row)

            self.current_row = None


# =========================
# ETF 数字转换
# =========================
def parse_flow_number(value):

    value = (
        value.replace(",", "")
        .replace("$", "")
        .strip()
    )

    if value in ("", "-", "–", "—"):
        return None

    # Farside 用括号表示负数
    # 例如 (144.6) = -144.6
    if value.startswith("(") and value.endswith(")"):

        return -float(value[1:-1])

    return float(value)


# =========================
# BTC ETF 资金流
# =========================
def get_btc_etf_flow():

    html = get_text(
        "https://farside.co.uk/bitcoin-etf-flow-all-data/"
    )

    parser = TableParser()
    parser.feed(html)

    # 从最新日期往前找
    for row in reversed(parser.rows):

        if len(row) < 5:
            continue

        date_text = row[0]

        if not re.fullmatch(
            r"\d{2} [A-Za-z]{3} \d{4}",
            date_text
        ):
            continue

        # 中间是各 ETF
        fund_values = row[1:-1]

        # 如果所有 ETF 都是 -
        # 说明当天数据还没有更新完成
        if all(
            x.strip() in ("", "-", "–", "—")
            for x in fund_values
        ):
            continue

        total = parse_flow_number(row[-1])

        if total is None:
            continue

        date_obj = datetime.strptime(
            date_text,
            "%d %b %Y"
        )

        return (
            date_obj.strftime("%m-%d"),
            total
        )

    raise ValueError(
        "没有找到有效 ETF 资金流数据"
    )


# =========================
# Telegram
# =========================
def send_telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload
    )

    with urllib.request.urlopen(
        req,
        timeout=20
    ) as response:

        return response.read()


def format_etf_amount(value):

    value = abs(value)

    if value >= 1000:
        return f"${value / 1000:.2f}B"

    return f"${value:.1f}M"


# =========================
# 主程序
# =========================
def main():

    btc_price, btc_change = get_btc()

    fng_value, fng_text = get_fear_greed()

    now = datetime.now(
        ZoneInfo("Asia/Shanghai")
    ).strftime("%Y-%m-%d %H:%M")

    # BTC 涨跌
    if btc_change >= 0:

        btc_icon = "🟢"
        btc_sign = "+"

    else:

        btc_icon = "🔴"
        btc_sign = ""

    # ETF
    try:

        etf_date, etf_flow = (
            get_btc_etf_flow()
        )

        if etf_flow > 0:

            etf_text = (
                f"🟢 净流入 "
                f"{format_etf_amount(etf_flow)}"
            )

        elif etf_flow < 0:

            etf_text = (
                f"🔴 净流出 "
                f"{format_etf_amount(etf_flow)}"
            )

        else:

            etf_text = "⚪ 净流入 $0"

        etf_line = (
            f"🏦 BTC现货ETF：{etf_text}\n"
            f"   数据日期：{etf_date}"
        )

    except Exception as e:

        print("ETF ERROR:", e)

        etf_line = (
            "🏦 BTC现货ETF：暂时获取失败"
        )

    message = (
        "📊 BTC 市场监控\n\n"

        f"₿ BTC：${btc_price:,.0f}\n"
        f"{btc_icon} 24H："
        f"{btc_sign}{btc_change:.2f}%\n\n"

        f"😨 恐惧贪婪："
        f"{fng_value}/100（{fng_text}）\n\n"

        f"{etf_line}\n\n"

        f"🕒 {now} 北京时间\n"

        "📡 数据源："
        "Binance / Alternative.me / Farside"
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
