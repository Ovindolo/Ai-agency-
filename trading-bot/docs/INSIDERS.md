# Insider and political data: setup and limits

Research and alerts only. Nothing in `apps/insiders` can place a trade (a test checks it).

## 1. Quiver in Claude (for chat research)
Quiver runs a remote MCP server at `https://mcp.quiverquant.com/`. Its API subscription starts at about
$30/month. In this account's connector directory it does not show up, so add it by hand.

Claude Code (terminal), with the key typed only into your own terminal, never into a chat:
```
claude mcp add --transport http quiverquant https://mcp.quiverquant.com/ --header "Authorization: Bearer $QUIVER_API_KEY"
claude mcp list        # then /mcp inside Claude Code should show it connected
```
claude.ai: Settings -> Connectors -> Add custom connector -> URL `https://mcp.quiverquant.com/`.

Smoke test once connected: ask for one recent insider filing and one congressional trade, and which
datasets the plan reaches; a locked dataset must be reported as locked.

## 2. The bot (runs on your machine or a VPS)
`.env`: `SEC_USER_AGENT="Your Name you@email"` (SEC rule), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`,
optional `QUIVER_API_KEY`.

```
make insiders        # report -> reports/INSIDERS.md; first run downloads ~60 days of Form 4 (~1-2k a day, cached)
make insiders-bot    # alerts + /clusters /ticker XYZ /rising from Telegram
```
On a $5-10 VPS, keep it running with systemd:
```
[Service]
WorkingDirectory=/home/you/Ai-agency-/trading-bot
EnvironmentFile=/home/you/Ai-agency-/trading-bot/.env
ExecStart=/usr/bin/python3 -m apps.insiders.bot
Restart=always
```

## 3. Timing
- Form 4: filed within 2 business days of the trade -> near-live, alert-worthy.
- Congress (STOCK Act): up to 45 days after the trade -> research context, never a trade signal.
Every line shows both the trade date and the filing date.

## 4. What the evidence says
- Cluster buys beat solitary insider buys: ~2.1% vs ~1.2% abnormal return the next month (Alldredge & Blank 2019).
- Only opportunistic insiders carry information; routine ones (same month every year) earn ~0 (Cohen, Malloy & Pomorski 2012, J. Finance: 82 bp/month for opportunistic).
- Congress as a whole does not beat the index (Belmont, Sacerdote et al. 2022, J. Public Economics); leadership is the exception reported in later work.
