#!/usr/bin/env python3
"""Zues store — one door, two faces, five shelves.
Agents (curl/no Accept) get JSON. Browsers (Accept: text/html) get black pages.
Every request is metered to usage.jsonl: route, ip, agent, status, latency.
/status is the demand readout. Free while we build; price shapes are already
attached so the till can be wired later without touching clients.
Copy rule: plain words, sell what buyers get, never how we get it."""
import html, json, os, re, time, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE = "/root/fastsig/state.json"
EVENTS = "/root/fastsig/events.jsonl"
SCORE = "/root/fastsig/scorecard.json"
USAGE = "/root/store/usage.jsonl"
STARTED = time.time()
PRICES = {"/verdict": 0.02, "/board": 0.05, "/scorecard": 0.02,
          "/extract": 0.01, "/summarize": 0.01, "/balance": 0.0, "/status": 0.0}
WINDOWS = [("Last 24 hours", 86400), ("Last 7 days", 7 * 86400),
           ("Last 30 days", 30 * 86400)]

PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{title} — ZUES</title></head>
<body style="background:#000;color:#eee;font-family:monospace;max-width:640px;margin:40px auto;padding:0 20px">
<h1 style="letter-spacing:6px">ZUES</h1>
{body}
<p style="color:#777;font-size:13px">Free while we build. Later: a few cents per check, paid from a crypto wallet. No account, no name.<br>
Building a bot? curl any page on this site for the same answer in JSON.</p></body></html>"""


# ---------- meter ----------
_hits = []          # in-memory: (ts, route, agent, status)
_today = [0]
_day = [time.strftime("%Y-%m-%d")]

def meter(route, agent, status, ms):
    now = time.time()
    day = time.strftime("%Y-%m-%d")
    if day != _day[0]:
        _day[0] = day
        _today[0] = 0
    _today[0] += 1
    _hits.append((now, route, agent, status))
    cutoff = now - 30 * 86400
    while _hits and _hits[0][0] < cutoff:
        _hits.pop(0)
    try:
        with open(USAGE, "a") as f:
            f.write(json.dumps({"ts": int(now), "route": route,
                                "ip": agent_ip[0], "agent": agent,
                                "status": status, "ms": ms}) + "\n")
    except Exception:
        pass

agent_ip = ["0.0.0.0"]

def load_usage():
    """Rebuild in-memory counters from disk so restarts don't lose history."""
    now = time.time()
    cutoff = now - 30 * 86400
    try:
        with open(USAGE) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("ts", 0) >= cutoff:
                        _hits.append((r["ts"], r.get("route", "?"),
                                      r.get("agent", "?"), r.get("status", 0)))
                except Exception:
                    pass
        _hits.sort()
    except Exception:
        pass

def status_stats():
    now = time.time()
    d24 = now - 86400
    d7 = now - 7 * 86400
    d30 = now - 30 * 86400
    routes_30 = {}
    agents = {}
    for ts, route, ag, st in _hits:
        if ts >= d30:
            routes_30[route] = routes_30.get(route, 0) + 1
            agents[ag] = agents.get(ag, 0) + 1
    top_agents = sorted(agents.items(), key=lambda kv: -kv[1])[:5]
    return {
        "uptime_s": int(now - STARTED),
        "hits_24h": len([h for h in _hits if h[0] >= d24]),
        "hits_7d": len([h for h in _hits if h[0] >= d7]),
        "hits_30d": len(_hits),
        "by_route_30d": routes_30,
        "top_agents_30d": top_agents,
        "note": "hits are requests to the store, paid or free",
    }


# ---------- whale data ----------
ALIAS = {"BITCOIN": "BTC", "ETHEREUM": "ETH", "SOLANA": "SOL", "RIPPLE": "XRP",
         "ZCASH": "ZEC", "CARDANO": "ADA", "DOGECOIN": "DOGE", "LITECOIN": "LTC",
         "MONERO": "XMR", "TRON": "TRX", "POLKADOT": "DOT", "CHAINLINK": "LINK",
         "AVALANCHE": "AVAX", "STELLAR": "XLM", "HYPERLIQUID": "HYPE",
         "NEAR PROTOCOL": "NEAR", "POLYGON": "POL", "BINANCE COIN": "BNB",
         "SHIBA INU": "SHIB", "UNISWAP": "UNI", "ARBITRUM": "ARB", "APTOS": "APT"}

def norm(token):
    t = (token or "").upper().strip()
    return ALIAS.get(t, t)

def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}

def load_events(window_s=86400):
    now = time.time()
    out = []
    try:
        with open(EVENTS) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if now - e.get("ts", 0) <= window_s:
                        out.append(e)
                except Exception:
                    pass
    except Exception:
        pass
    return out

def verdict(token):
    token = norm(token)
    state = load_state()
    longs = shorts = 0
    net = 0.0
    for addr, w in state.items():
        szi = w.get("pos", {}).get(token)
        if szi is None:
            continue
        net += szi
        if szi > 0:
            longs += 1
        elif szi < 0:
            shorts += 1
    events = [e for e in load_events() if e.get("coin", "").upper() == token]
    if longs == shorts == 0 and not events:
        return {"token": token, "verdict": "NO_DATA",
                "note": "none of the tracked wallets hold or touched this token"}
    if longs > shorts and net > 0:
        v = "LONG-BIASED"
    elif shorts > longs and net < 0:
        v = "SHORT-BIASED"
    else:
        v = "MIXED"
    return {
        "token": token,
        "verdict": v,
        "whales": {"long": longs, "short": shorts},
        "net_exposure_units": round(net, 4),
        "events_24h": len(events),
        "last_events": [{k: e.get(k) for k in ("ts", "coin", "action", "szi", "px")}
                        for e in events[-3:]],
        "price_usdc": PRICES["/verdict"],
        "source": "tracked big-trader positions",
        "as_of": int(time.time()),
    }

def board():
    """One call: every coin the tracked group actually holds or touched, ranked
    by how one-sided the group's lean is."""
    state = load_state()
    counts = {}
    for addr, w in state.items():
        pos = w.get("pos", {})
        for tok, szi in pos.items():
            c = counts.setdefault(tok, {"long": 0, "short": 0, "net": 0.0})
            c["net"] += szi
            if szi > 0:
                c["long"] += 1
            elif szi < 0:
                c["short"] += 1
    events = load_events()
    ev_count = {}
    for e in events:
        tok = e.get("coin", "").upper()
        ev_count[tok] = ev_count.get(tok, 0) + 1
        counts.setdefault(tok, {"long": 0, "short": 0, "net": 0.0})
    rows = []
    for tok, c in counts.items():
        l, s = c["long"], c["short"]
        if l > s and c["net"] > 0:
            v = "LONG-BIASED"
        elif s > l and c["net"] < 0:
            v = "SHORT-BIASED"
        elif l or s or ev_count.get(tok):
            v = "MIXED"
        else:
            continue
        rows.append({"token": tok, "verdict": v,
                     "long": l, "short": s,
                     "net_exposure_units": round(c["net"], 4),
                     "events_24h": ev_count.get(tok, 0)})
    rows.sort(key=lambda r: (-abs(r["long"] - r["short"]), -r["events_24h"]))
    return {"as_of": int(time.time()),
            "watched_wallets": len(state),
            "count": len(rows),
            "board": rows[:25],
            "price_usdc": PRICES["/board"],
            "note": "ranked most one-sided first. Use /verdict?token=X for the full read on one coin."}

def score_rows():
    try:
        recs = json.load(open(SCORE))
    except Exception:
        recs = []
    now = time.time()
    rows, summary = [], []
    for name, secs in WINDOWS:
        w = [r for r in recs if now - r.get("ts", 0) <= secs]
        decided = [r for r in w if r.get("px1h") is not None and r.get("px0")]
        if decided:
            moves = [((r["px1h"] - r["px0"]) / r["px0"]) * 100
                     * (1 if r["side"] == "UP" else -1) for r in decided]
            hits = len([m for m in moves if m > 0])
            avg = sum(moves) / len(moves)
            summary.append(f"<p><b>{name}:</b> {len(w)} green lights · "
                           f"{len(decided)} decided · {hits} went our way · "
                           f"average move {avg:+.1f}%</p>")
        else:
            summary.append(f"<p><b>{name}:</b> {len(w)} green lights · "
                           f"1-hour checks still coming</p>")
    cutoff = now - 30 * 86400
    recent = sorted([r for r in recs if now - r.get("ts", 0) <= cutoff],
                    key=lambda r: -r.get("ts", 0))[:200]
    if not recent:
        rows.append("<li>No green lights yet — the record starts on the first one.</li>")
    for r in recent:
        t = time.strftime("%b %d %H:%M", time.gmtime(r["ts"]))
        p1 = r.get("px1h")
        if p1 and r.get("px0"):
            mv = ((p1 - r["px0"]) / r["px0"]) * 100 * (1 if r["side"] == "UP" else -1)
            mark = ("✔" if mv > 0 else "✘") + f" {mv:+.1f}% at 1h"
            col = "#7CFC9A" if mv > 0 else "#FF6B6B"
        else:
            mark, col = "deciding…", "#777"
        p0 = r.get('px0') or 0
        ps = f"${p0:,.2f}" if p0 < 10 else f"${p0:,.0f}"
        rows.append(f"<li style=margin:6px 0>{t} — {r['coin']} read {r['side']} "
                    f"at {ps} · <span style=color:{col}>{mark}</span></li>")
    return "".join(summary), "".join(rows) or "<li>Nothing yet.</li>"


# ---------- text shelf (stdlib only) ----------
STOP = set("a about above after again against all am an and any are aren't as at be because "
           "been before being below between both but by can cannot could couldn't did didn't do "
           "does doesn't doing don't down during each few for from further had hadn't has hasn't "
           "have haven't having he her here hers herself him himself his how i if in into is isn't "
           "it its itself just let's me more most must my myself no nor not of off on once only or "
           "other ought our ours ourselves out over own same shan't she should shouldn't so some "
           "such than that the their theirs them themselves then there these they this those "
           "through to too under until up very was wasn't we were weren't what when where which "
           "while who whom why with won't would wouldn't you your yours yourself yourselves "
           "also however said says like will one two new first last get got make made".split())

def _words(text):
    return [w for w in re.findall(r"[a-zA-Z']{2,}", text.lower()) if w not in STOP]

def extract(text):
    words = _words(text)
    if not words:
        return {"keywords": [], "note": "no usable words found"}
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    scored = []
    for i, s in enumerate(sents):
        ws = _words(s)
        if not ws:
            continue
        score = sum(freq.get(w, 0) for w in ws) / (len(ws) + 4)
        scored.append((score, i, s))
    scored.sort(reverse=True)
    key_sents = [s for _, _, s in scored[:3]]
    key_sents.sort(key=lambda s: text.find(s))
    return {"keywords": [w for w, _ in top],
            "word_count": len(words),
            "key_sentences": key_sents,
            "price_usdc": PRICES["/extract"]}

def summarize(text, max_sents=3):
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sents) <= max_sents:
        return {"summary": sents, "sentences_in": len(sents),
                "price_usdc": PRICES["/summarize"]}
    words = _words(text)
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    scored = []
    for i, s in enumerate(sents):
        ws = _words(s)
        if not ws:
            continue
        scored.append((sum(freq.get(w, 0) for w in ws) / len(ws), i, s))
    scored.sort(reverse=True)
    picked = sorted(scored[:max_sents], key=lambda t: t[1])
    return {"summary": [s for _, _, s in picked],
            "sentences_in": len(sents), "sentences_out": len(picked),
            "price_usdc": PRICES["/summarize"]}


# ---------- machine-readable docs ----------
def llms_txt():
    return """# Zues
> Reads of where big crypto traders are positioned, for people and bots. Plain answers, no account, no name.

## Endpoints
- GET /verdict?token=BTC — one line read on a coin: is big money leaning up, down, or split. JSON.
- GET /board — all coins the tracked big traders hold or touched, ranked most one-sided first. JSON.
- GET /scorecard — our track record: every strong group signal and whether the coin went where we read it 1 hour later. JSON.
- GET /extract?text=... — keywords and key sentences from a block of text. JSON.
- GET /summarize?text=... — short version of a block of text. JSON.
- GET /status — store uptime, request counts, data freshness. JSON.
- GET /balance — store till state. JSON.
- GET /pricing.json — prices per endpoint. JSON.
- GET /openapi.json — machine-readable API spec. JSON.
- POST /mcp — Model Context Protocol. Load Zues as a tool set in an agent: check_coin, the_board, track_record, key_words, shorten.

## Notes
- Agents: curl any URL for JSON. Browsers get a plain web page. Same answer either way.
- Free while building. Prices are already attached in every JSON response (price_usdc).
- Payment later: x402, USDC. No signup ever.
"""

def openapi():
    def op(path, desc, params=None):
        p = {"get": {"summary": desc, "operationId": path.strip("/").replace("?", "_").replace("=", "").replace("&", "_"),
                     "responses": {"200": {"description": "OK"},
                                   "404": {"description": "no data for that token"}},
                     "x-price-usdc": PRICES.get(path.split("?")[0], 0.0)}}
        if params:
            p["get"]["parameters"] = params
        return p
    return {
        "openapi": "3.0.0",
        "info": {"title": "Zues store API",
                 "description": "Big-trader position reads, ranked board, track record, and light text tools. Keyless, no signup, crypto-paid (x402, planned). Free while building.",
                 "version": "0.3.0"},
        "servers": [{"url": "https://zues.sarl"}],
        "paths": {
            "/verdict": op("/verdict", "One-line read: is big money leaning up, down, or split on a coin",
                           [{"name": "token", "in": "query", "required": True,
                             "schema": {"type": "string"}, "description": "Coin symbol, e.g. BTC, ZEC, HYPE"}]),
            "/board": op("/board", "All watched coins ranked most one-sided first"),
            "/scorecard": op("/scorecard", "Track record: every strong group signal and its 1-hour outcome"),
            "/extract": op("/extract", "Keywords and key sentences from text",
                           [{"name": "text", "in": "query", "required": True, "schema": {"type": "string"}}]),
            "/summarize": op("/summarize", "Short version of a block of text",
                             [{"name": "text", "in": "query", "required": True, "schema": {"type": "string"}}]),
            "/status": op("/status", "Store health: uptime, request counts, data freshness"),
            "/balance": op("/balance", "Store till state"),
            "/pricing.json": op("/pricing.json", "Prices per endpoint"),
        },
    }

def pricing():
    return {
        "store": "zues.sarl",
        "currency": "USDC",
        "payment": "x402 (planned; free while building)",
        "endpoints": {
            "/verdict?token=BTC": {"price_usdc": PRICES["/verdict"], "unit": "per check"},
            "/board": {"price_usdc": PRICES["/board"], "unit": "per pull"},
            "/scorecard": {"price_usdc": PRICES["/scorecard"], "unit": "per pull"},
            "/extract?text=...": {"price_usdc": PRICES["/extract"], "unit": "per text"},
            "/summarize?text=...": {"price_usdc": PRICES["/summarize"], "unit": "per text"},
            "/status": {"price_usdc": 0.0, "unit": "free"},
            "/balance": {"price_usdc": 0.0, "unit": "free"},
        },
        "note": "No account, no name. Free while we build; prices are attached in every response.",
    }


# ---------- html faces ----------
def v_html(v):
    t = html.escape(v["token"])
    search = ('<form method=get action=/verdict>'
              '<input name=token placeholder="try BTC, ZEC, HYPE..." '
              'style="background:#111;color:#eee;border:1px solid #444;padding:8px;width:60%">'
              '<button style="background:#eee;color:#000;border:0;padding:8px 14px">check</button></form>')
    if v["verdict"] == "NO_DATA":
        body = (f"<h2>{t}: no watch yet</h2>"
                f"<p>No big-trader activity on {t} in the last 24 hours.</p>{search}")
        return 404, "no watch", body
    plain = {"LONG-BIASED": ("#7CFC9A", "Most of the big traders we watch are betting this coin goes UP."),
             "SHORT-BIASED": ("#FF6B6B", "Most of the big traders we watch are betting this coin goes DOWN."),
             "MIXED": ("#FFD166", "The big traders disagree. There is no clear direction right now.")}[v["verdict"]]
    w = v["whales"]
    last = v.get("last_events") or []
    shown = []
    for e in last:
        act = {"ADD": "bought more", "TRIM": "sold some",
               "CLOSE": "sold everything", "OPEN": "opened a bet",
               "FLIP": "switched sides"}.get(e.get("action"), e.get("action"))
        n = abs(e.get("szi") or 0)
        shown.append(f"<li>{act} — {n:,.0f} {t} at about ${e.get('px'):,.0f}"
                     if e.get("px") else f"<li>{act} — {n:,.0f} {t}")
    last_html = ("<p>Latest moves:</p><ul style=padding-left:20px>" + "".join(shown) + "</ul>") if shown else ""
    body = (f"<h2>{t}: <span style=color:{plain[0]}>{v['verdict'].split('-')[0].title()}-biased</span></h2>"
            f"<p style='font-size:17px'>{plain[1]}</p>"
            f"<p>Right now {w['long']} big traders are betting up and {w['short']} are betting down. "
            f"{v['events_24h']} moves among them in the last 24 hours.</p>"
            f"{last_html}{search}")
    return 200, v["verdict"], body

def home_html():
    return 200, "ZUES", (
        "<p>Before you bet on a coin, know where the big money already is.</p>"
        "<p>Type any coin. We tell you in one line: are the big traders leaning "
        "up, leaning down, or fighting each other.</p>"
        "<p><a href=\"/board\" style=color:#7CFC9A>See every coin on the board</a> · "
        "<a href=\"/scorecard\" style=color:#7CFC9A>See our track record</a></p>"
        '<form method=get action=/verdict>'
        '<input name=token placeholder="BTC, ZEC, HYPE..." '
        'style="background:#111;color:#eee;border:1px solid #444;padding:8px;width:60%">'
        '<button style="background:#eee;color:#000;border:0;padding:8px 14px">check a coin</button></form>')

def board_html(b):
    rows = []
    col = {"LONG-BIASED": "#7CFC9A", "SHORT-BIASED": "#FF6B6B", "MIXED": "#FFD166"}
    for r in b["board"]:
        side = "up" if "LONG" in r["verdict"] else ("down" if "SHORT" in r["verdict"] else "split")
        rows.append(f"<li style=margin:4px 0>{html.escape(r['token'])} — leaning {side} "
                    f"({r['long']} up / {r['short']} down, {r['events_24h']} moves today) "
                    f"<span style=color:{col[r['verdict']]}>{r['verdict'].split('-')[0].title()}</span></li>")
    body = ("<h2>The board</h2>"
            "<p>Every coin the big traders we watch hold or touched today, ranked by how "
            "one-sided they lean. The top of this list is where the group feels strongest.</p>"
            "<p><b>" + str(b["count"]) + " coins · " + str(b["watched_wallets"]) + " big wallets watched</b></p>"
            "<ul style=padding-left:20px>" + "".join(rows) + "</ul>"
            '<form method=get action=/verdict>'
            '<input name=token placeholder="full read on one coin..." '
            'style="background:#111;color:#eee;border:1px solid #444;padding:8px;width:60%">'
            '<button style="background:#eee;color:#000;border:0;padding:8px 14px">check a coin</button></form>')
    return 200, "The board", body

def text_html(kind):
    act = "/extract" if kind == "extract" else "/summarize"
    what = ("Paste a block of text. We pull out the words and sentences that carry it."
            if kind == "extract" else
            "Paste a block of text. We give you back the short version.")
    body = (f"<h2>{'Pull the key words' if kind == 'extract' else 'Shorten a text'}</h2>"
            f"<p>{what}</p>"
            f'<form method=get action={act}>'
            f'<textarea name=text rows=6 style="background:#111;color:#eee;border:1px solid #444;'
            f'width:100%;box-sizing:border-box"></textarea><br>'
            f'<button style="background:#eee;color:#000;border:0;padding:8px 14px;margin-top:8px">'
            f'{"find key words" if kind == "extract" else "shorten"}</button></form>')
    return 200, kind.title(), body

def text_result_html(kind, res):
    if kind == "extract":
        body = ("<h2>Key words</h2>"
                "<p><b>" + ", ".join(html.escape(w) for w in res.get("keywords", [])) + "</b></p>")
        ks = res.get("key_sentences", [])
        if ks:
            body += "<p>Sentences that carry the text:</p><ul style=padding-left:20px>" + \
                    "".join(f"<li>{html.escape(s)}</li>" for s in ks) + "</ul>"
    else:
        body = "<h2>Short version</h2><ul style=padding-left:20px>" + \
               "".join(f"<li>{html.escape(s)}</li>" for s in res.get("summary", [])) + "</ul>"
    body += ('<p><a href="/board" style=color:#7CFC9A>Back to the board</a> · '
             '<a href="/" style=color:#7CFC9A>Home</a></p>')
    return 200, kind.title(), body

def status_html(s, fresh):
    rows = [f"<li>Uptime: {s['uptime_s'] // 3600}h {(s['uptime_s'] % 3600) // 60}m</li>",
            f"<li>Requests last 24h: {s['hits_24h']}</li>",
            f"<li>Requests last 7 days: {s['hits_7d']}</li>",
            f"<li>Requests last 30 days: {s['hits_30d']}</li>"]
    by_route = "".join(f"<li>{html.escape(k)}: {v}</li>" for k, v in
                       sorted(s["by_route_30d"].items(), key=lambda kv: -kv[1]))
    agents = "".join(f"<li>{html.escape(k or 'unknown')}: {v}</li>" for k, v in s["top_agents_30d"])
    body = ("<h2>Store status</h2><ul style=padding-left:20px>" + "".join(rows) + "</ul>"
            f"<p>Big-trader data last updated: {fresh}</p>"
            "<p>Where requests went, last 30 days:</p><ul style=padding-left:20px>" + by_route + "</ul>"
            "<p>Top callers, last 30 days:</p><ul style=padding-left:20px>" + agents + "</ul>")
    return 200, "Status", body

def score_html():
    s, rows = score_rows()
    body = ("<h2>Track record</h2>"
            "<p>Every time the whole group bets together AND keeps adding fresh "
            "money, we call it a <b style=color:#7CFC9A>green light</b>. "
            "This page shows each one, and whether the coin went where we read "
            "it one hour later. Nothing hidden, nothing removed.</p>"
            f"{s}<ul style=padding-left:20px>{rows}</ul>")
    return 200, "Track record", body


class H(BaseHTTPRequestHandler):
    def wants_html(self):
        return "text/html" in (self.headers.get("Accept") or "")

    def send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        t0 = time.time()
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        u = urllib.parse.parse_qs(parsed.query)
        agent_ip[0] = (self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                       or self.client_address[0])
        ua = (self.headers.get("User-Agent") or "").split()[0][:60] if self.headers.get("User-Agent") else "unknown"
        code_holder = [0]

        def out(code, ctype, body):
            code_holder[0] = code
            self.send(code, ctype, body)

        try:
            self.route(route, u, out, ua)
        except Exception:
            code_holder[0] = 500
            try:
                out(500, "application/json", b'{"error":"internal"}')
            except Exception:
                pass
        meter(route, ua, code_holder[0], round((time.time() - t0) * 1000, 1))

    def route(self, parsed_path, u, out, ua):
        if parsed_path == "/llms.txt":
            out(200, "text/plain", llms_txt().encode())
            return
        if parsed_path == "/openapi.json":
            out(200, "application/json", json.dumps(openapi()).encode())
            return
        if parsed_path == "/pricing.json":
            out(200, "application/json", json.dumps(pricing()).encode())
            return
        if parsed_path == "/balance":
            out(200, "application/json", json.dumps(
                {"balance": 0.0, "currency": "USDC", "ts": int(time.time())}).encode())
            return

        if self.wants_html():
            if parsed_path == "/verdict":
                code, title, body = v_html(verdict((u.get("token") or [""])[0]))
            elif parsed_path == "/scorecard":
                code, title, body = score_html()
            elif parsed_path == "/board":
                code, title, body = board_html(board())
            elif parsed_path in ("/extract", "/summarize"):
                txt = (u.get("text") or [""])[0][:8000]
                if txt.strip():
                    res = extract(txt) if parsed_path == "/extract" else summarize(txt)
                    code, title, body = text_result_html(parsed_path.strip("/"), res)
                else:
                    code, title, body = text_html(parsed_path.strip("/"))
            elif parsed_path == "/status":
                s = status_stats()
                code, title, body = status_html(s, data_fresh())
            else:
                code, title, body = home_html()
            out(code, "text/html", PAGE.format(
                title=html.escape(title), body=body).encode())
            return

        if parsed_path == "/verdict":
            v = verdict((u.get("token") or [""])[0])
            code = 200 if v.get("verdict") != "NO_DATA" else 404
            out(code, "application/json", json.dumps(v).encode())
        elif parsed_path == "/board":
            out(200, "application/json", json.dumps(board()).encode())
        elif parsed_path == "/scorecard":
            try:
                recs = json.load(open(SCORE))
            except Exception:
                recs = []
            out(200, "application/json", json.dumps(
                {"green_lights": recs,
                 "note": "every green light: coin, side, price at signal, price 1h and 24h later"}).encode())
        elif parsed_path in ("/extract", "/summarize"):
            txt = (u.get("text") or [""])[0][:8000]
            if not txt.strip():
                out(400, "application/json", b'{"error":"pass ?text=your text"}')
                return
            res = extract(txt) if parsed_path == "/extract" else summarize(txt)
            out(200, "application/json", json.dumps(res).encode())
        elif parsed_path == "/status":
            out(200, "application/json", json.dumps(
                {**status_stats(), "data_fresh": data_fresh()}).encode())
        elif parsed_path == "/":
            out(200, "application/json", json.dumps({
                "store": "zues",
                "what": "reads of where big crypto traders are positioned, plus light text tools",
                "how": "curl any endpoint; JSON back. No account, no name.",
                "endpoints": {
                    "/verdict?token=BTC": "one-line read on a coin",
                    "/board": "all watched coins, ranked most one-sided first",
                    "/scorecard": "our track record, every signal and outcome",
                    "/extract?text=...": "keywords and key sentences",
                    "/summarize?text=...": "short version of a text",
                    "/status": "store health and request counts",
                    "/balance": "till state",
                    "/pricing.json": "prices",
                    "/openapi.json": "machine-readable spec",
                    "/llms.txt": "plain-text site guide for agents",
                },
                "price_usdc": pricing()["endpoints"],
            }).encode())
        else:
            out(404, "application/json", b'{"error":"not found","try":"/ for the endpoint list"}')

    def log_message(self, fmt, *a):
        pass  # meter covers it


# ---------- MCP (agents load Zues as a tool set) ----------
PROTO = "2025-03-26"
TOOLS = [
    {"name": "check_coin",
     "description": "One-line read on a coin: are the big traders leaning up, leaning down, or fighting each other. Counts of big traders on each side, net position, and their latest moves.",
     "inputSchema": {"type": "object",
                     "properties": {"token": {"type": "string",
                                              "description": "Coin symbol, e.g. BTC, ZEC, HYPE"}},
                     "required": ["token"]}},
    {"name": "the_board",
     "description": "Every coin the tracked big traders hold or touched today, ranked most one-sided first. Use this to see where the group feels strongest before picking a coin.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "track_record",
     "description": "Every strong group signal and whether the coin went where we read it one hour later. Nothing hidden, nothing removed.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "key_words",
     "description": "Pull the words and sentences that carry a block of text.",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string", "description": "The text to read"}},
                     "required": ["text"]}},
    {"name": "shorten",
     "description": "The short version of a block of text.",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string", "description": "The text to shorten"}},
                     "required": ["text"]}},
]

def mcp_result(payload):
    if not isinstance(payload, dict):
        return {"error": "bad request"}
    method = payload.get("method")
    mid = payload.get("id")
    params = payload.get("params") or {}

    def resp(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        return resp({"protocolVersion": PROTO,
                     "capabilities": {"tools": {}},
                     "serverInfo": {"name": "zues",
                                    "title": "Zues — big-trader reads + text tools",
                                    "version": "0.3.0"}})
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return resp({})
    if method == "tools/list":
        return resp({"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "check_coin":
                data = verdict(args.get("token", ""))
                txt = (f"{data['token']}: {data['verdict']}. "
                       f"{data['whales']['long']} big traders up, {data['whales']['short']} down. "
                       f"{data['events_24h']} moves in 24h."
                       ) if data["verdict"] != "NO_DATA" else data["note"]
                return resp({"content": [{"type": "text", "text": txt}],
                             "data": data})
            if name == "the_board":
                b = board()
                lines = [f"{r['token']} — {r['verdict'].split('-')[0].title()} "
                         f"({r['long']} up / {r['short']} down, {r['events_24h']} moves today)"
                         for r in b["board"]]
                return resp({"content": [{"type": "text", "text": "\n".join(lines) or "no coins watched yet"}],
                             "data": b})
            if name == "track_record":
                try:
                    recs = json.load(open(SCORE))
                except Exception:
                    recs = []
                return resp({"content": [{"type": "text", "text": json.dumps(recs[-30:])}],
                             "data": {"green_lights": recs}})
            if name == "key_words":
                return resp({"content": [{"type": "text",
                                          "text": json.dumps(extract(args.get("text", "")[:8000]))}]})
            if name == "shorten":
                return resp({"content": [{"type": "text",
                                          "text": json.dumps(summarize(args.get("text", "")[:8000]))}]})
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"unknown tool {name}"}}
        except Exception as e:
            return resp({"content": [{"type": "text", "text": f"error: {e}"}],
                         "isError": True})
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found"}}


def do_POST(self):
    t0 = time.time()
    parsed = urllib.parse.urlparse(self.path)
    route = parsed.path
    agent_ip[0] = (self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                   or self.client_address[0])
    ua = (self.headers.get("User-Agent") or "").split()[0][:60] if self.headers.get("User-Agent") else "unknown"
    code_holder = [0]

    def out(code, ctype, body):
        code_holder[0] = code
        self.send(code, ctype, body)

    if route == "/mcp":
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(length, 1_000_000)) if length else b""
            payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
            reply = mcp_result(payload if isinstance(payload, dict) else {})
            if reply is None:
                code_holder[0] = 202
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                out(200, "application/json", json.dumps(reply).encode())
        except Exception:
            try:
                out(500, "application/json",
                    b'{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}')
            except Exception:
                pass
    else:
        out(404, "application/json", b'{"error":"not found","try":"/ for the endpoint list"}')
    meter(route, ua, code_holder[0], round((time.time() - t0) * 1000, 1))


def data_fresh():
    try:
        s = load_state()
        newest = max((w.get("ts", 0) for w in s.values()), default=0)
        if not newest:
            return "unknown"
        age = time.time() - newest
        return f"{int(age // 60)} minutes ago"
    except Exception:
        return "unknown"


H.do_POST = do_POST  # attach the MCP POST handler to the request class


if __name__ == "__main__":
    import sys
    load_usage()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    HTTPServer(("127.0.0.1", port), H).serve_forever()
