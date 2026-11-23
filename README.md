# Zues — big-trader reads for crypto

Check any coin and get one line: are the big traders leaning up, leaning down, or fighting each other. Backed by a public track record — every strong signal and its outcome, nothing hidden.

No account. No name. Free while building.

## What you get

- **check_coin** — one-line read on a coin: big-trader counts on each side, net position, latest moves
- **the_board** — every coin the tracked group holds or touched, ranked most one-sided first
- **track_record** — every strong group signal and whether the coin went where we read it 1 hour later
- **key_words** — pull the words and sentences that carry a block of text
- **shorten** — the short version of a block of text

## Use it two ways

**1. Plain HTTP (curl, any agent, any language):**

```
curl https://zues.sarl/verdict?token=BTC
curl https://zues.sarl/board
curl https://zues.sarl/scorecard
```

Full endpoint list: `https://zues.sarl/llms.txt` · spec: `/openapi.json` · prices: `/pricing.json`

**2. MCP (load Zues as a tool set in your agent):**

Endpoint: `https://zues.sarl/mcp` (Streamable HTTP, no auth)

Claude Code:
```
claude mcp add --transport http zues https://zues.sarl/mcp
```

Any MCP client config:
```json
{"mcpServers": {"zues": {"url": "https://zues.sarl/mcp"}}}
```

## The server

`server.py` in this repo is the whole store — one Python file, stdlib only, no dependencies. Runs behind any TLS proxy:

```
python3 server.py 8080
```

- Agents (no `Accept: text/html`) get JSON on every route
- Browsers get a plain black page, no JavaScript
- Every request is metered to `usage.jsonl` (route, IP, agent, status, latency)
- `/status` is the public demand readout

## Track record

Every time the whole tracked group bets together and keeps adding fresh money, that's a green light. The scorecard shows each one and whether the coin went where we read it: https://zues.sarl/scorecard

## Notes

- Free while building. Prices are already attached in every JSON response (`price_usdc`). Payment lands later via x402 (USDC) — no signup ever.
- Data source: public positions of tracked big traders on Hyperliquid. We sell the read, not the method.
