# btc-telegram-monitor

升级版 BTC Telegram 市场监控。

## 已支持

- `/now`
- `/today`
- `/todayfull`
- `/yesterday`
- `/week`
- `/etf`
- `/signals`
- `/history`
- `/collect`
- `/repair`
- `/quota`
- `/db`
- `/backup`
- `/export`
- `/sources`
- `/status`
- `/debug`
- `/help`

## 数据源

Binance、Alternative.me、SoSoValue、DefiLlama、Coinbase。

Perp 数据需要 `COINGLASS_API_KEY`；MVRV-Z 需要 `BGEOMETRICS_API_KEY`。未配置时机器人会明确显示“未配置/无法确认”，不会伪造数据。

## GitHub Actions

Workflow 每 5 分钟运行一次，用于：
1. 检查 Telegram 新命令；
2. 执行命令；
3. 在北京时间每天 10:00 左右自动发送完整版日报和信号；
4. 把 `bot_state.json` 和 `market_history.json` 提交回仓库，形成历史记录。

## Secrets

已有：
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SOSOVALUE_API_KEY`

可选：
- `COINGLASS_API_KEY`
- `BGEOMETRICS_API_KEY`

> 建议将仓库设为 Private。
