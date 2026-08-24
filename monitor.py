import os
import json
import csv
import io
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = str(os.environ["TELEGRAM_CHAT_ID"])
SOSOVALUE_API_KEY = os.environ.get("SOSOVALUE_API_KEY", "")
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "")
BGEOMETRICS_API_KEY = os.environ.get("BGEOMETRICS_API_KEY", "")

TZ = ZoneInfo("Asia/Shanghai")
STATE_FILE = "bot_state.json"
HISTORY_FILE = "market_history.json"
VERSION = "2.0.0"


def now_cn():
    return datetime.now(TZ)


def iso_now():
    return now_cn().isoformat(timespec="seconds")


def get_json(url, extra_headers=None, timeout=30):
    headers = {"User-Agent": "btc-telegram-monitor/2.0", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code}: {body[:300]}") from e


def get_bytes(url, extra_headers=None, timeout=30):
    headers = {"User-Agent": "btc-telegram-monitor/2.0"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_state():
    return load_json_file(STATE_FILE, {
        "update_offset": 0,
        "last_collection": None,
        "last_daily_push": None,
        "api_calls": {},
        "runs": 0,
    })


def save_state(state):
    save_json_file(STATE_FILE, state)


def load_history():
    return load_json_file(HISTORY_FILE, [])


def save_history(history):
    history = history[-500:]
    save_json_file(HISTORY_FILE, history)


def api_count(state, name):
    state.setdefault("api_calls", {})
    state["api_calls"][name] = state["api_calls"].get(name, 0) + 1


def get_btc(state):
    urls = [
        "https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT",
        "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT",
    ]
    last = None
    for url in urls:
        try:
            data = get_json(url)
            api_count(state, "Binance")
            return {
                "price": float(data["lastPrice"]),
                "change_24h": float(data["priceChangePercent"]),
                "high_24h": float(data["highPrice"]),
                "low_24h": float(data["lowPrice"]),
                "volume_24h": float(data["quoteVolume"]),
            }
        except Exception as e:
            last = e
    raise last


def get_fear_greed(state):
    data = get_json("https://api.alternative.me/fng/?limit=1")
    api_count(state, "Alternative.me")
    item = data["data"][0]
    cn = {
        "Extreme Fear": "极度恐惧",
        "Fear": "恐惧",
        "Neutral": "中性",
        "Greed": "贪婪",
        "Extreme Greed": "极度贪婪",
    }
    return {"value": int(item["value"]), "text": cn.get(item["value_classification"], item["value_classification"])}


def get_btc_etf_history(state):
    if not SOSOVALUE_API_KEY:
        raise RuntimeError("未配置 SOSOVALUE_API_KEY")
    params = urllib.parse.urlencode({"symbol": "BTC", "country_code": "US", "limit": 20})
    url = "https://openapi.sosovalue.com/openapi/v1/etfs/summary-history?" + params
    raw = get_json(url, {"x-soso-api-key": SOSOVALUE_API_KEY})
    api_count(state, "SoSoValue")
    if isinstance(raw, dict) and "data" in raw:
        if raw.get("code") not in (None, 0, "0"):
            raise RuntimeError("SoSoValue API错误：" + str(raw.get("message")))
        data = raw["data"]
    else:
        data = raw
    rows = []
    for item in data or []:
        d = item.get("date")
        flow = item.get("total_net_inflow")
        if d and flow is not None:
            rows.append({"date": str(d), "flow": float(flow)})
    if not rows:
        raise RuntimeError("SoSoValue没有有效ETF数据")
    rows.sort(key=lambda x: x["date"], reverse=True)
    return rows


def get_coinglass_data(state):
    if not COINGLASS_API_KEY:
        raise RuntimeError("未配置 COINGLASS_API_KEY")

    url = "https://open-api.coinglass.com/public/v2/open_interest?symbol=BTC&exchange=Binance"

    headers = {
        "coinglassSecret": COINGLASS_API_KEY
    }

    raw = get_json(url, headers)

    api_count(state, "CoinGlass")

    return {
    "symbol": "BTC",
    "open_interest": raw
}
    

def get_stablecoins(state):
    url = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
    data = get_json(url)
    api_count(state, "DefiLlama")
    rows = data.get("peggedAssets", data if isinstance(data, list) else [])
    total = 0.0
    usdt = 0.0
    usdc = 0.0
    for x in rows:
        circ = x.get("circulating") or {}
        usd = float(circ.get("peggedUSD") or 0)
        total += usd
        sym = str(x.get("symbol") or x.get("name") or "").upper()
        if sym == "USDT":
            usdt += usd
        elif sym == "USDC":
            usdc += usd
    return {"total": total, "usdt": usdt, "usdc": usdc}


def get_chains_tvl(state):
    data = get_json("https://api.llama.fi/v2/chains")
    api_count(state, "DefiLlama")
    wanted = {"Ethereum", "Solana", "Base", "Sui", "Monad"}
    result = {}
    total = 0.0
    for x in data:
        name = x.get("name")
        tvl = x.get("tvl")
        if tvl is None:
            continue
        tvl = float(tvl)
        total += tvl
        if name in wanted:
            result[name] = tvl
    result["Total chains TVL"] = total
    return result


def get_dex_volume(state):
    url = "https://api.llama.fi/overview/dexs?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyVolume"
    data = get_json(url, timeout=45)
    api_count(state, "DefiLlama")
    return {
        "total24h": float(data.get("total24h") or 0),
        "total7d": float(data.get("total7d") or 0),
        "change_1d": float(data.get("change_1d") or 0),
        "change_7d": float(data.get("change_7d") or 0),
    }


def get_perp_volume(state):
    # DefiLlama's current derivatives overview is a Pro endpoint.
    # If COINGLASS_API_KEY is configured, use its public market summary.
    if not COINGLASS_API_KEY:
        return {"available": False, "reason": "未配置 COINGLASS_API_KEY"}
    url = "https://open-api-v4.coinglass.com/api/futures/coins-markets"
    try:
        data = get_json(url, {"CG-API-KEY": COINGLASS_API_KEY}, timeout=30)
        api_count(state, "CoinGlass")
        items = data.get("data", []) if isinstance(data, dict) else []
        total = 0.0
        for x in items:
            v = x.get("volume24h")
            if v is not None:
                total += float(v)
        return {"available": True, "total24h": total}
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}


def get_coinbase_premium(state, btc_price):
    try:
        cb = get_json("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
        api_count(state, "Coinbase")
        cb_price = float(cb["price"])
        premium = (cb_price / btc_price - 1.0) * 100
        return {"available": True, "coinbase_price": cb_price, "premium": premium}
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}


def get_mvrv_z(state):
    """Fetch the latest daily MVRV Z-Score from BGeometrics."""
    if not BGEOMETRICS_API_KEY:
        return {
            "available": False,
            "reason": "未配置 BGEOMETRICS_API_KEY"
        }

    urls = [
        "https://bitcoin-data.com/v1/mvrv-zscore/last",
        "https://bitcoin-data.com/v1/mvrv-zscore?limit=1",
    ]

    errors = []

    for base_url in urls:
        try:
            separator = "&" if "?" in base_url else "?"
            url = (
                base_url
                + separator
                + "token="
                + urllib.parse.quote(BGEOMETRICS_API_KEY)
            )

            data = get_json(url, timeout=20)

            print(
                "BGEOMETRICS RAW:",
                json.dumps(data, ensure_ascii=False),
                flush=True
            )

            api_count(state, "BGeometrics")

            # API可能直接返回对象，也可能返回数组
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get("data", data)
                if isinstance(rows, dict):
                    rows = [rows]
            else:
                rows = []

            if not rows:
                raise RuntimeError("API返回为空")

            item = rows[-1]

            if not isinstance(item, dict):
                raise RuntimeError("API返回的数据格式异常")

            # BGeometrics日期字段
            date_value = (
                item.get("d")
                or item.get("date")
                or item.get("timestamp")
                or ""
            )

            # 优先寻找明确的MVRV-Z字段
            possible_keys = [
                "mvrvZ",
                "mvrv_z",
                "mvrv-zscore",
                "mvrv_zscore",
                "mvrvZscore",
                "zscore",
                "z_score",
                "value",
            ]

            value = None

            for key in possible_keys:
                if item.get(key) is not None:
                    value = item.get(key)
                    break

            if value is None:
                # 如果字段名不同，尝试寻找唯一的数字字段
                numeric_candidates = []

                for key, val in item.items():
                    if key in ("unixTs", "timestamp"):
                        continue

                    try:
                        numeric_value = float(val)

                        # MVRV-Z通常在较小的数值范围内
                        if -20 <= numeric_value <= 20:
                            numeric_candidates.append(
                                (key, numeric_value)
                            )
                    except (TypeError, ValueError):
                        continue

                if len(numeric_candidates) == 1:
                    value = numeric_candidates[0][1]

            if value is None:
                raise RuntimeError(
                    "API返回成功，但没有找到MVRV-Z数值；"
                    f"字段={list(item.keys())}"
                )

            return {
                "available": True,
                "value": float(value),
                "date": str(date_value)
            }

        except Exception as e:
            errors.append(str(e)[:300])

    return {
        "available": False,
        "reason": "；".join(errors)[:500]
    }

def collect_snapshot(state):
    btc = get_btc(state)
    fng = get_fear_greed(state)

    snapshot = {
        "timestamp": iso_now(),
        "date": now_cn().strftime("%Y-%m-%d"),
        "btc": btc,
        "fear_greed": fng,
        "sources": ["Binance", "Alternative.me"],
    }

    try:
        etfs = get_btc_etf_history(state)
        snapshot["etf"] = etfs
        snapshot["sources"].append("SoSoValue")
    except Exception as e:
        snapshot["etf_error"] = str(e)

    
    try:
        cg = get_coinglass_data(state)
        snapshot["coinglass"] = cg
        snapshot["sources"].append("CoinGlass")
    except Exception as e:
        snapshot["coinglass_error"] = str(e)

    
    for key, fn in [
        ("stablecoins", get_stablecoins),
        ("tvl", get_chains_tvl),
        ("dex", get_dex_volume),
        ("perp", get_perp_volume),
        ("coinbase", lambda s: get_coinbase_premium(s, btc["price"])),
        ("mvrv_z", get_mvrv_z),
    ]:
        try:
            snapshot[key] = fn(state)
        except Exception as e:
            snapshot[key] = {"available": False, "reason": str(e)[:160]}

    snapshot["sources"] = list(dict.fromkeys(snapshot["sources"] + [
        "DefiLlama", "Coinbase", "CoinGlass", "BGeometrics"
    ]))
    return snapshot


def fmt_usd(v, signed=False):
    if v is None:
        return "N/A"
    sign = ""
    if signed:
        sign = "+" if v > 0 else ("-" if v < 0 else "")
    v = abs(float(v))
    if v >= 1e9:
        return f"{sign}${v/1e9:.2f}B"
    if v >= 1e6:
        return f"{sign}${v/1e6:.1f}M"
    if v >= 1e3:
        return f"{sign}${v/1e3:.1f}K"
    return f"{sign}${v:,.0f}"


def fmt_pct(v):
    return f"{v:+.2f}%"


def latest_etf(snapshot):
    rows = snapshot.get("etf") or []
    return rows[0] if rows else None


def signal(snapshot):
    score = 0
    reasons = []
    risks = []

    etf = latest_etf(snapshot)
    if etf:
        if etf["flow"] > 0:
            score += 2
            reasons.append(f"BTC ETF净流入 {fmt_usd(etf['flow'], True)}")
        elif etf["flow"] < 0:
            score -= 2
            risks.append(f"BTC ETF净流出 {fmt_usd(etf['flow'], True)}")

    st = snapshot.get("stablecoins", {})
    if st.get("total", 0) > 0:
        score += 1
        reasons.append("稳定币总市值可用")

    tvl = snapshot.get("tvl", {})
    if tvl.get("Total chains TVL", 0) > 0:
        score += 1
        reasons.append("链TVL维持正向资金环境")

    cb = snapshot.get("coinbase", {})
    if cb.get("available"):
        if cb["premium"] > 0.05:
            score += 1
            reasons.append(f"Coinbase Premium {cb['premium']:+.2f}%")
        elif cb["premium"] < -0.05:
            score -= 1
            risks.append(f"Coinbase Premium {cb['premium']:+.2f}%")

    m = snapshot.get("mvrv_z", {})
    if m.get("available"):
        if m["value"] < 2.5:
            score += 1
            reasons.append(f"MVRV-Z {m['value']:.2f}，未处高估区")
        elif m["value"] > 6:
            score -= 2
            risks.append(f"MVRV-Z {m['value']:.2f}，估值偏热")

    if score >= 4:
        label, icon = "偏积极", "🟢"
    elif score >= 2:
        label, icon = "略偏积极", "🟢"
    elif score <= -3:
        label, icon = "偏谨慎", "🔴"
    elif score <= -1:
        label, icon = "略偏谨慎", "🟠"
    else:
        label, icon = "中性", "🟡"

    return {"score": score, "label": label, "icon": icon, "reasons": reasons, "risks": risks}


def format_today(snapshot, full=False):
    btc = snapshot["btc"]
    fg = snapshot["fear_greed"]
    etf = latest_etf(snapshot)
    st = snapshot.get("stablecoins", {})
    tvl = snapshot.get("tvl", {})
    dex = snapshot.get("dex", {})
    perp = snapshot.get("perp", {})
    cb = snapshot.get("coinbase", {})
    m = snapshot.get("mvrv_z", {})

    lines = [
        "📊 BTC 市场监控",
        "",
        f"₿ BTC：${btc['price']:,.0f}",
        f"{'🟢' if btc['change_24h'] >= 0 else '🔴'} 24H：{fmt_pct(btc['change_24h'])}",
        f"🔺 24H高点：${btc['high_24h']:,.0f}",
        f"🔻 24H低点：${btc['low_24h']:,.0f}",
        "",
        f"😨 恐惧贪婪：{fg['value']}/100（{fg['text']}）",
        "",
        f"🏦 BTC现货ETF：{('🟢 净流入 ' if etf and etf['flow'] > 0 else '🔴 净流出 ' if etf and etf['flow'] < 0 else '⚪ 暂无')}{fmt_usd(etf['flow']) if etf else 'N/A'}",
        f"   数据日期：{etf['date'] if etf else 'N/A'}",
    ]

    if full:
        lines += [
            "",
            "💵 稳定币",
            f"总市值：{fmt_usd(st.get('total'))}",
            f"USDT：{fmt_usd(st.get('usdt'))}",
            f"USDC：{fmt_usd(st.get('usdc'))}",
            "",
            "🔒 DeFi / Chain TVL",
            f"总链TVL：{fmt_usd(tvl.get('Total chains TVL'))}",
            f"Ethereum：{fmt_usd(tvl.get('Ethereum'))}",
            f"Solana：{fmt_usd(tvl.get('Solana'))}",
            f"Base：{fmt_usd(tvl.get('Base'))}",
            f"Sui：{fmt_usd(tvl.get('Sui'))}",
            f"Monad：{fmt_usd(tvl.get('Monad'))}",
            "",
            "🔄 交易量",
            f"DEX 24H：{fmt_usd(dex.get('total24h'))}（{fmt_pct(dex.get('change_1d', 0))}）",
            f"DEX 7D：{fmt_usd(dex.get('total7d'))}",
            f"Perp 24H：{fmt_usd(perp.get('total24h')) if perp.get('available') else '暂未配置/无法确认'}",
            "",
            "🇺🇸 Coinbase",
            f"Premium：{cb.get('premium'):+.2f}%" if cb.get("available") else "Premium：暂未确认",
            "",
            "📐 MVRV-Z",
            f"{m['value']:.2f}" if m.get("available") else "暂未配置/无法确认",
        ]

    lines += [
        "",
        f"🕒 {snapshot['timestamp'].replace('T', ' ')} 北京时间",
        "📡 数据源：Binance / Alternative.me / SoSoValue / DefiLlama / Coinbase",
    ]
    return "\n".join(lines)


def format_signals(snapshot):
    s = signal(snapshot)
    lines = [
        "📡 BTC 市场综合信号",
        "",
        f"综合：{s['icon']} {s['label']}",
        f"规则分：{s['score']:+d}",
        "",
        "🟢 支持因素",
    ]
    lines += [f"• {x}" for x in s["reasons"]] or ["• 暂无足够数据"]
    lines += ["", "⚠️ 风险因素"]
    lines += [f"• {x}" for x in s["risks"]] or ["• 暂无明显负面信号"]
    lines += [
        "",
        "📌 说明：这是规则型市场仪表盘，不是自动买卖建议。",
        f"🕒 {snapshot['timestamp'].replace('T', ' ')} 北京时间",
    ]
    return "\n".join(lines)


def send_telegram(message, chat_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": str(chat_id or CHAT_ID),
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def send_document(filename, content, chat_id=None):
    boundary = "----btcmonitorboundary"
    body = []
    def field(name, value):
        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    field("chat_id", str(chat_id or CHAT_ID))
    body.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\nContent-Type: text/plain\r\n\r\n".encode()
    )
    body.append(content.encode("utf-8"))
    body.append(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
        data=b"".join(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def get_updates(state):
    offset = int(state.get("update_offset", 0))
    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/getUpdates?" + urllib.parse.urlencode({
        "offset": offset,
        "timeout": 1,
        "allowed_updates": json.dumps(["message"]),
    })
    data = get_json(url, timeout=10)
    return data.get("result", [])


def is_allowed_chat(chat_id):
    return str(chat_id) == CHAT_ID


def latest_snapshot(history):
    return history[-1] if history else None


def command_help():
    return """📚 BTC 市场监控命令

/now        实时刷新核心数据
/today      今日简版
/todayfull   今日完整版
/yesterday  昨日最近快照
/week       最近5个ETF交易日
/etf         BTC ETF资金流
/signals     综合市场信号
/history     最近历史数据
/collect     手动采集并保存
/repair      重新采集缺失数据
/quota       API调用统计
/db          数据库状态
/backup      发送当前数据库备份
/export      导出历史CSV
/sources     数据源与口径
/status      机器人运行状态
/debug       数据采集诊断
/help        显示帮助"""


def handle_command(cmd, state, history):
    c = cmd.strip().split()[0].lower().split("@")[0]

    if c in ("/start", "/help"):
        send_telegram(command_help())
        return history

    if c in ("/now", "/today", "/todayfull", "/collect", "/repair", "/signals", "/debug"):
        snapshot = collect_snapshot(state)
        if c in ("/collect", "/repair"):
            history.append(snapshot)
            save_history(history)
            state["last_collection"] = snapshot["timestamp"]
        elif c == "/signals":
            send_telegram(format_signals(snapshot))
            return history
        elif c == "/debug":
            lines = ["🧪 数据采集诊断", ""]
            for k, v in snapshot.items():
                if isinstance(v, dict) and v.get("available") is False:
                    lines.append(f"🔴 {k}: {v.get('reason', '失败')}")
                elif k.endswith("_error"):
                    lines.append(f"🔴 {k}: {v}")
                else:
                    lines.append(f"🟢 {k}: OK")
            send_telegram("\n".join(lines))
            return history
        else:
            if not history or history[-1].get("timestamp") != snapshot["timestamp"]:
                history.append(snapshot)
                save_history(history)
            if c == "/now":
                send_telegram(format_today(snapshot, full=True))
            elif c == "/todayfull":
                send_telegram(format_today(snapshot, full=True))
            else:
                send_telegram(format_today(snapshot, full=False))
            return history

    snap = latest_snapshot(history)

    if c == "/yesterday":
        target = (now_cn().date() - timedelta(days=1)).isoformat()
        rows = [x for x in history if x.get("date") == target]
        send_telegram(format_today(rows[-1], full=True) if rows else "暂无昨日快照。")
    elif c == "/etf":
        try:
            if not snap:
                snap = collect_snapshot(state)
            rows = snap.get("etf") or []
            if not rows:
                send_telegram("⚠️ 当前没有ETF数据")
            else:
                lines = ["🏦 BTC现货ETF历史", ""]
                lines += [f"{x['date']}：{fmt_usd(x['flow'], True)}" for x in rows[:10]]
                send_telegram("\n".join(lines))
        except Exception as e:
            send_telegram(f"❌ ETF查询失败：{str(e)}")
    elif c == "/week":
        if not snap:
            snap = collect_snapshot(state)
        rows = (snap.get("etf") or [])[:5]
        total = sum(x["flow"] for x in rows)
        lines = ["📅 最近5个ETF交易日", ""]
        lines += [f"{x['date']}：{fmt_usd(x['flow'], True)}" for x in rows]
        lines += ["", f"合计：{fmt_usd(total, True)}"]
        send_telegram("\n".join(lines))
    elif c == "/signals":
        if not snap:
            snap = collect_snapshot(state)
        send_telegram(format_signals(snap))
    elif c == "/history":
        rows = history[-10:]
        if not rows:
            send_telegram("暂无历史数据。")
        else:
            lines = ["🗃 最近10次快照", ""]
            for x in reversed(rows):
                b = x["btc"]
                lines.append(f"{x['timestamp'].replace('T',' ')}｜${b['price']:,.0f}｜{b['change_24h']:+.2f}%")
            send_telegram("\n".join(lines))
    elif c == "/quota":
        lines = ["📊 API调用统计", ""]
        for k, v in sorted(state.get("api_calls", {}).items()):
            lines.append(f"{k}：{v}")
        send_telegram("\n".join(lines))
    elif c == "/db":
        send_telegram(f"🗃 数据库状态\n记录数：{len(history)}\n最新记录：{history[-1]['timestamp'] if history else '无'}\n版本：{VERSION}")
    elif c == "/backup":
        content = json.dumps({"state": state, "history": history}, ensure_ascii=False, indent=2)
        send_document("btc_monitor_backup.json", content)
    elif c == "/export":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["timestamp", "btc_price", "btc_change_24h", "fear_greed", "btc_etf_flow"])
        for x in history:
            e = latest_etf(x)
            w.writerow([x.get("timestamp"), x["btc"]["price"], x["btc"]["change_24h"], x["fear_greed"]["value"], e["flow"] if e else ""])
        send_document("btc_market_history.csv", out.getvalue())
    elif c == "/sources":
        send_telegram("""📡 数据源与口径

BTC：Binance BTCUSDT 24H ticker
恐惧贪婪：Alternative.me
BTC ETF：SoSoValue ETF summary history
稳定币：DefiLlama Stablecoins
Chain TVL：DefiLlama /v2/chains
DEX：DefiLlama /overview/dexs
Coinbase Premium：Coinbase BTC-USD vs Binance BTCUSDT
Perp：需配置 COINGLASS_API_KEY；未配置时不虚构数据
MVRV-Z：需配置 BGEOMETRICS_API_KEY；未配置时不虚构数据""")
    elif c == "/status":
        send_telegram(f"🟢 BTC Monitor {VERSION}\nGitHub Actions模式\n运行次数：{state.get('runs',0)}\n上次采集：{state.get('last_collection') or '无'}\n上次日报：{state.get('last_daily_push') or '无'}")
    else:
        send_telegram("❓ 未知命令。发送 /help 查看全部功能。")
    return history


def daily_due(state):
    n = now_cn()
    # Daily push at 10:00-10:04 Beijing time, with Actions running every 5 minutes.
    today = n.strftime("%Y-%m-%d")
    return n.hour == 10 and n.minute < 5 and state.get("last_daily_push") != today


def run():
    state = load_state()
    history = load_history()
    state["runs"] = int(state.get("runs", 0)) + 1

    # Handle Telegram commands.
    try:
        updates = get_updates(state)
        for u in updates:
            msg = u.get("message") or {}
            chat = msg.get("chat", {})
            text = msg.get("text", "")
            if not text or not is_allowed_chat(chat.get("id")):
                continue
            history = handle_command(text, state, history)
            state["update_offset"] = max(
                int(state.get("update_offset", 0)),
                int(u["update_id"]) + 1
            )
    except Exception as e:
        print("UPDATE ERROR:", e)

    # Daily automatic full report.
    if daily_due(state):
        try:
            snapshot = collect_snapshot(state)
            history.append(snapshot)
            save_history(history)
            send_telegram(format_today(snapshot, full=True))
            send_telegram(format_signals(snapshot))
            state["last_collection"] = snapshot["timestamp"]
            state["last_daily_push"] = now_cn().strftime("%Y-%m-%d")
        except Exception as e:
            print("DAILY ERROR:", e)

    save_state(state)


if __name__ == "__main__":
    run()
