import os
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SOSOVALUE_API_KEY = os.environ["SOSOVALUE_API_KEY"]


# =========================
# 通用请求
# =========================
def get_json(url, extra_headers=None):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(
        url,
        headers=headers
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=30
        ) as response:

            return json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as e:

        body = e.read().decode(
            "utf-8",
            errors="ignore"
        )

        raise RuntimeError(
            f"HTTP {e.code}: {body[:300]}"
        ) from e


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
            change = float(
                data["priceChangePercent"]
            )

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

    classification = (
        item["value_classification"]
    )

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
# SoSoValue BTC ETF
# =========================
def get_btc_etf_flow():

    params = urllib.parse.urlencode({
        "symbol": "BTC",
        "country_code": "US",
        "limit": 10
    })

    url = (
        "https://openapi.sosovalue.com/"
        "openapi/v1/etfs/summary-history?"
        + params
    )

    raw = get_json(
        url,
        {
            "x-soso-api-key":
                SOSOVALUE_API_KEY
        }
    )

    # SoSoValue 标准返回格式
    # {"code":0,"message":"success","data":[...]}
    if isinstance(raw, dict) and "data" in raw:

        code = raw.get("code")

        if code not in (None, 0, "0"):

            raise RuntimeError(
                "SoSoValue API错误："
                + str(raw.get("message"))
            )

        data = raw["data"]

    else:
        data = raw

    if not isinstance(data, list) or not data:

        raise RuntimeError(
            "SoSoValue没有返回ETF数据"
        )

    # 官方接口最新日期优先
    for item in data:

        date_text = item.get("date")

        flow = item.get(
            "total_net_inflow"
        )

        if (
            date_text
            and flow is not None
        ):

            flow = float(flow)

            try:

                date_show = datetime.strptime(
                    date_text,
                    "%Y-%m-%d"
                ).strftime("%m-%d")

            except Exception:

                date_show = date_text

            return date_show, flow

    raise RuntimeError(
        "没有找到有效ETF资金流数据"
    )


# =========================
# 金额格式
# =========================
def format_usd(value):

    value = abs(value)

    if value >= 1_000_000_000:

        return (
            f"${value / 1_000_000_000:.2f}B"
        )

    if value >= 1_000_000:

        return (
            f"${value / 1_000_000:.1f}M"
        )

    if value >= 1_000:

        return (
            f"${value / 1_000:.1f}K"
        )

    return f"${value:,.0f}"


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


# =========================
# 主程序
# =========================
def main():

    btc_price, btc_change = get_btc()

    fng_value, fng_text = (
        get_fear_greed()
    )

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
                "🟢 净流入 "
                + format_usd(etf_flow)
            )

        elif etf_flow < 0:

            etf_text = (
                "🔴 净流出 "
                + format_usd(etf_flow)
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
        "Binance / Alternative.me / SoSoValue"
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
