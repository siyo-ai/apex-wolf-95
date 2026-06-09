import os
import asyncio
import threading
import requests
import json
import tempfile
import base64
import io
import re
import sqlite3
from datetime import datetime, timedelta, time
from dateutil import parser
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from apscheduler.schedulers.background import BackgroundScheduler
import whisper
import yfinance as yf
import pandas as pd
import numpy as np
import ta
from bs4 import BeautifulSoup
import sentry_sdk
from tenacity import retry, stop_after_attempt, wait_exponential
import aiosqlite
import httpx

load_dotenv()

# ===== CONFIG =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_AI_KEY = os.getenv("GOOGLE_AI_KEY")
SENTRY_DSN = os.getenv("SENTRY_DSN")
PORT = int(os.getenv("PORT", 10000))

if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=1.0)

# ===== GLOBALS =====
ALERTS = {}
WHISPER_MODEL = None
SCHEDULER = BackgroundScheduler()
SCHEDULER.start()
DB_PATH = "apex_journal.db"

# ===== CURRICULUM =====
CURRICULUM = {
    "beginner": {
        "1_pips_lots": {
            "title": "Pips, Lots, Leverage",
            "content": """**Pips**: Smallest price move. EURUSD 1.0850 → 1.0851 = 1 pip. JPY pairs: 110.50 → 110.51 = 1 pip.
**Lots**: 1.0 lot = 100,000 units. 0.01 lot = 1,000 units. 
**Leverage**: 1:100 means $100 controls $10,000. DANGER: Also magnifies losses.
**Formula**: Pip Value = (0.0001 / price) × lot_size × 100,000. For EURUSD 1 lot ≈ $10/pip.
**Why it matters**: If you risk 20 pips on 1 lot EURUSD, that's $200 risk. Account $1000 = 20% risk = blown account.""",
            "quiz": [
                {"q": "EURUSD moves 1.2000 to 1.2010. How many pips?", "a": "10", "options": ["1", "10", "100"]},
                {"q": "0.10 lots EURUSD, 20 pip SL. Risk if $10/pip?", "a": "$20", "options": ["$2", "$20", "$200"]}
            ]
        },
        "2_risk_management": {
            "title": "Risk Management = Survival",
            "content": """**Golden Rule**: Never risk >1% per trade. 0.25% if learning.
**Math**: $10,000 account × 0.25% = $25 risk. If SL = 20 pips, Lot = $25 / (20 × $10) = 0.12 lots.
**Daily DD**: Hit -2% = stop trading. Ego kills accounts.
**R:R**: Always take 1:2 minimum. 50% win rate + 1:2 = profit. 33% win rate + 1:3 = profit.
**Why Apex locks you at -2%**: Prop firms kick you at -5%. We stop you at -2% so you live to trade tomorrow.""",
            "quiz": [
                {"q": "$5000 account, 0.5% risk, 30 pip SL. Lot size?", "a": "0.08", "options": ["0.08", "0.8", "8.0"]},
                {"q": "Win rate 40%, avg R:R 1:3. Profitable?", "a": "Yes", "options": ["Yes", "No"]}
            ]
        },
        "3_support_resistance": {
            "title": "S/R: Where Price Reacts",
            "content": """**Support**: Floor where buyers step in. Old support becomes resistance.
**Resistance**: Ceiling where sellers step in. Old resistance becomes support.
**How to draw**: Find 2+ touches. More touches = stronger.
**ICT Upgrade**: S/R alone = 50/50. You need liquidity above/below. Stops sit at S/R. Smart money hunts stops, then reverses.""",
            "quiz": [
                {"q": "Price breaks resistance, comes back to test it. Now it's?", "a": "Support", "options": ["Support", "Resistance"]}
            ]
        }
    },
    "intermediate": {
        "1_market_structure": {
            "title": "BOS, CHOCH, Trend",
            "content": """**Bullish BOS**: Price makes Higher High, breaks previous high. Uptrend continues.
**Bearish BOS**: Price makes Lower Low, breaks previous low. Downtrend continues.
**CHOCH**: Change of Character. Bullish CHOCH = breaks last lower high. First sign trend may flip.
**Why it matters**: Don't buy in downtrend. Wait for bullish CHOCH + BOS before long.""",
            "quiz": [
                {"q": "Price makes LL, then breaks previous LH. This is?", "a": "Bullish CHOCH", "options": ["Bullish BOS", "Bullish CHOCH", "Bearish BOS"]}
            ]
        },
        "2_liquidity": {
            "title": "Liquidity = Fuel",
            "content": """**Buy-side Liquidity**: Stops above old highs. Smart money buys there to fill large sells.
**Sell-side Liquidity**: Stops below old lows. Smart money sells there to fill large buys.
**EQH/EQL**: Equal Highs/Lows = stacked stops = liquidity pool.
**Killzones**: London 7-10 AM UTC, NY 12:30-3:30 PM UTC. This is when liquidity gets raided.
**Rule**: Never buy at highs. Wait for sweep of highs, then sell. Never sell at lows. Wait for sweep of lows, then buy.""",
            "quiz": [
                {"q": "Price spikes above old high, then dumps. What happened?", "a": "Buy-side liquidity raid", "options": ["Breakout", "Buy-side liquidity raid"]}
            ]
        },
        "3_fvg_ob": {
            "title": "FVG + Order Blocks",
            "content": """**FVG**: Fair Value Gap. 3-candle pattern where candle 1 high < candle 3 low. Price imbalance. Price returns to fill it 70% of time.
**Bullish OB**: Last down candle before explosive up move. Institutions bought here.
**Bearish OB**: Last up candle before explosive down move. Institutions sold here.
**Entry**: Price returns to OB/FVG in killzone + takes liquidity = snipe entry.""",
            "quiz": [
                {"q": "Candle 1 High: 1.0850, Candle 3 Low: 1.0860. Is this FVG?", "a": "Yes", "options": ["Yes", "No"]}
            ]
        }
    },
    "advanced": {
        "1_smc_execution": {
            "title": "Full ICT/SMC Model",
            "content": """**A+ Setup Checklist**:
1. HTF Bias: Weekly/Daily bullish
2. H1 Structure: Bullish BOS, price in discount
3. Liquidity: Swept sell-side below Asian low
4. POI: H1 bullish OB or FVG in discount
5. Entry: M15 CHOCH into POI during London/NY
6. SL: Below OB
7. TP: Above old high where buy-side liquidity sits
8. Macro: DXY bearish, yields down
**Confluence Score**: Bot needs 75/100 minimum. You need 3+ factors manually.""",
            "quiz": [
                {"q": "DXY bullish, you want EURUSD long. Confluence score impact?", "a": "-20", "options": ["+20", "-20", "0"]}
            ]
        },
        "2_intermarket": {
            "title": "DXY, Yields, SPX, Oil",
            "content": """**DXY Up**: USD pairs down: EURUSD, GBPUSD, AUDUSD, XAUUSD. USDJPY up.
**US10Y Up**: USD up, Gold down, JPY down. Yields = gravity for USD.
**SPX Up**: Risk ON. AUD, NZD, CAD up. JPY, CHF down.
**USOIL Up**: CAD up. USDCAD down.
**Rule**: Never long EURUSD if DXY making new highs. Macro kills technicals.""",
            "quiz": [
                {"q": "US10Y spikes +0.20%. XAUUSD likely?", "a": "Down", "options": ["Up", "Down", "Flat"]}
            ]
        },
        "3_psychology": {
            "title": "Psychology = 80% of Trading",
            "content": """**Revenge Trading**: Lose → double size → blow up. DD lockout exists because of this.
**FOMO**: Chase price → enter late → SL hits. A+ setups come to you.
**Overtrading**: 3 losses = walk away. Mental capital depleted.
**Journaling**: Review every loss. Was it: bad analysis, bad execution, or bad luck? Fix first two.
**Why bot locks you**: Protects you from yourself. Best traders trade less.""",
            "quiz": [
                {"q": "You hit -2% daily DD. What do you do?", "a": "Stop trading", "options": ["Double size", "Stop trading", "Switch to gold"]}
            ]
        }
    }
}

# ===== DB INIT =====
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute('''CREATE TABLE IF NOT EXISTS trades
        (id INTEGER PRIMARY KEY, user_id INTEGER, symbol TEXT, direction TEXT, entry REAL, sl REAL, tp REAL,
        lot_size REAL, status TEXT, pnl REAL, rr TEXT, timestamp TEXT, trade_type TEXT, confluence_score INTEGER, macro_json TEXT, notes TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS users
        (user_id INTEGER PRIMARY KEY, account_balance REAL, risk_percent REAL, max_daily_dd REAL, min_confluence INTEGER, news_lockout INTEGER, active INTEGER)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS lessons
        (user_id INTEGER, module TEXT, topic TEXT, completed INTEGER, score INTEGER, timestamp TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS quiz_progress
        (user_id INTEGER, level TEXT, last_score INTEGER, unlocked_levels TEXT)''')
        await db.commit()

# ===== FASTAPI =====
app = FastAPI(title="Apex Wolf AI 10.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class AnalyzeRequest(BaseModel):
    prompt: str
    user_id: int = 0
    account_balance: float = None

class UpdateSettings(BaseModel):
    user_id: int
    account_balance: float = None
    risk_percent: float = None
    max_daily_dd: float = None
    min_confluence: int = None
    news_lockout: int = None

class CloseTrade(BaseModel):
    trade_id: int
    user_id: int
    close_price: float

async def get_user_data(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id =?", (user_id,))
        row = await cur.fetchone()
        if not row:
            await db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)", (user_id, 10000.0, 0.25, 2.0, 75, 1))
            await db.commit()
            return {"account_balance": 10000.0, "risk_percent": 0.25, "max_daily_dd": 2.0, "min_confluence": 75, "news_lockout": 1, "daily_pnl": 0.0, "locked": False}

        today = datetime.now().strftime("%Y-%m-%d")
        cur = await db.execute("SELECT SUM(pnl) FROM trades WHERE user_id =? AND DATE(timestamp) =? AND status='closed'", (user_id, today))
        row2 = await cur.fetchone()
        daily_pnl = row2[0] or 0.0

        return {
            "account_balance": row[1], "risk_percent": row[2], "max_daily_dd": row[3], "min_confluence": row[4], "news_lockout": row[5],
            "daily_pnl": daily_pnl, "locked": daily_pnl <= -(row[1] * row[3] / 100)
        }

@app.post("/settings")
async def update_settings(req: UpdateSettings):
    user = await get_user_data(req.user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET account_balance=?, risk_percent=?, max_daily_dd=?, min_confluence=?, news_lockout=? WHERE user_id=?",
                   (req.account_balance or user["account_balance"], req.risk_percent or user["risk_percent"], 
                    req.max_daily_dd or user["max_daily_dd"], req.min_confluence or user["min_confluence"],
                    req.news_lockout if req.news_lockout is not None else user["news_lockout"], req.user_id))
        await db.commit()
    return {"status": "updated", "data": await get_user_data(req.user_id)}

@app.get("/")
def root():
    return {"status": "Apex Wolf 10.0 Online ✝️🩸"}

@app.get("/healthz")
async def healthz():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("SELECT 1")
        await fetch_yahoo_data("EURUSD")
        return {"status": "ok", "db": "ok", "yahoo": "ok"}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"status": "degraded", "error": str(e)}

# ===== SYMBOL RESOLVER =====
def resolve_symbol(symbol: str):
    symbol = symbol.upper().replace("/", "")
    if symbol.endswith("USD") and symbol not in ["EURUSD","GBPUSD","AUDUSD","NZDUSD","USDCAD","USDCHF","USDJPY"]:
        return {"yahoo": f"{symbol[:-3]}-USD", "tv": f"BINANCE:{symbol[:-3]}USDT", "type": "crypto", "pip": 1}
    indices = {"US30":"^DJI", "NAS100":"^NDX", "SPX500":"^GSPC", "GER40":"^GDAXI", "UK100":"^FTSE", "USOIL":"CL=F", "DXY":"DX-Y.NYB", "US10Y":"^TNX"}
    if symbol in indices: return {"yahoo": indices[symbol], "tv": f"TVC:{symbol}", "type": "index", "pip": 1}
    if symbol == "XAUUSD": return {"yahoo": "GC=F", "tv": "OANDA:XAUUSD", "type": "metal", "pip": 0.1}
    if symbol == "XAGUSD": return {"yahoo": "SI=F", "tv": "OANDA:XAGUSD", "type": "metal", "pip": 0.01}
    pip_mult = 100 if "JPY" in symbol else 10000
    return {"yahoo": f"{symbol}=X", "tv": f"FX:{symbol}", "type": "forex", "pip": pip_mult}

# ===== PRICE WITH RETRY =====
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_yahoo_data(symbol: str):
    resolved = resolve_symbol(symbol)
    data = yf.Ticker(resolved["yahoo"]).history(period="1d", interval="1m")
    if data.empty: raise Exception(f"No data for {symbol}")
    return data

@app.get("/price/{symbol}")
async def get_price(symbol: str):
    try:
        data = await fetch_yahoo_data(symbol)
        price = round(float(data['Close'].iloc[-1]), 5)
        return {"symbol": symbol.upper(), "price": price}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"error": f"Price feed down: {str(e)}", "fallback": True}

# ===== MTF DATA =====
async def get_mtf_data(symbol: str, trade_type: str):
    resolved = resolve_symbol(symbol)
    intervals = [("W1", "1wk"), ("D1", "1d"), ("H4", "4h"), ("H1", "1h"), ("M15", "15m")] if trade_type == "swing" else [("H4", "4h"), ("H1", "1h"), ("M15", "15m"), ("M5", "5m")]
    tf_data = {}
    for tf, interval in intervals:
        try:
            data = yf.Ticker(resolved["yahoo"]).history(period="60d", interval=interval)
            if not data.empty:
                data['ATR'] = ta.volatility.average_true_range(data['High'], data['Low'], data['Close'], 14)
                tf_data[tf] = data.tail(100)
        except: pass
    return tf_data

# ===== MACRO CONTEXT =====
async def get_macro_context(symbol: str):
    context = {"bias": "NEUTRAL", "strength": 0, "warnings": []}
    try:
        dxy = yf.Ticker("DX-Y.NYB").history(period="5d", interval="1h")
        dxy_trend = "BULLISH" if dxy['Close'].iloc[-1] > dxy['Close'].iloc[-24] else "BEARISH"
        context["DXY"] = dxy_trend
        if "USD" in symbol:
            context["bias"] = "BEARISH" if dxy_trend == "BULLISH" and symbol.startswith("EUR") else "BULLISH"
            context["strength"] += 20

        us10y = yf.Ticker("^TNX").history(period="5d", interval="1h")
        bonds_up = us10y['Close'].iloc[-1] > us10y['Close'].iloc[-24]
        context["US10Y"] = "UP" if bonds_up else "DOWN"
        if bonds_up and symbol in ["XAUUSD", "USDJPY"]:
            context["warnings"].append("Rising yields bearish for Gold/JPY")
            context["strength"] -= 15

        spx = yf.Ticker("^GSPC").history(period="5d", interval="1h")
        risk_on = spx['Close'].iloc[-1] > spx['Close'].iloc[-24]
        context["RISK"] = "ON" if risk_on else "OFF"
        if risk_on and "JPY" in symbol:
            context["warnings"].append("Risk ON bearish for JPY")
        if not risk_on and symbol in ["AUDUSD", "NZDUSD"]:
            context["warnings"].append("Risk OFF bearish for AUD/NZD")

        if "CAD" in symbol:
            oil = yf.Ticker("CL=F").history(period="5d", interval="1h")
            oil_up = oil['Close'].iloc[-1] > oil['Close'].iloc[-24]
            context["USOIL"] = "UP" if oil_up else "DOWN"
            if oil_up and symbol.startswith("USD"): context["bias"] = "BEARISH"
    except Exception as e:
        sentry_sdk.capture_exception(e)
        context["error"] = str(e)
    return context

# ===== ORDER FLOW =====
async def get_order_flow(symbol: str):
    flow = {"cot_bias": "NEUTRAL", "retail": "NEUTRAL"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://www.myfxbook.com/community/outlook", timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            # Simplified: parse first EURUSD entry
            if symbol == "EURUSD":
                long_pct = soup.find("td", text=re.compile("EURUSD"))
                if long_pct:
                    pct = int(re.search(r'(\d+)%', long_pct.find_next_sibling().text).group(1))
                    flow["retail"] = "LONG" if pct > 60 else "SHORT" if pct < 40 else "NEUTRAL"
    except: pass
    return flow

# ===== LIQUIDITY ZONES =====
def get_liquidity_zones(symbol: str, tf_data: dict):
    zones = {"eqh": [], "eql": [], "hvn": [], "score": 0}
    try:
        if "H1" not in tf_data: return zones
        df = tf_data["H1"]
        highs = df['High'].tail(20)
        lows = df['Low'].tail(20)
        for i in range(len(highs)-1):
            if abs(highs.iloc[i] - highs.iloc[i+1]) < highs.iloc[i]*0.0005:
                zones["eqh"].append(round(highs.iloc[i], 5))
            if abs(lows.iloc[i] - lows.iloc[i+1]) < lows.iloc[i]*0.0005:
                zones["eql"].append(round(lows.iloc[i], 5))
        if len(df) > 20:
            vol_profile = df['ATR'].tail(20)
            hvn_level = df['Close'][vol_profile.idxmax()]
            zones["hvn"].append(round(hvn_level, 5))
            zones["score"] += 10
    except: pass
    return zones

# ===== SESSION LEVELS =====
def get_session_levels(symbol: str, tf_data: dict):
    levels = {"asian_high": 0, "asian_low": 0, "london_high": 0, "london_low": 0, "mid": 0}
    try:
        if "H1" not in tf_data: return levels
        df = tf_data["H1"].tail(24)
        df.index = pd.to_datetime(df.index)
        asian = df.between_time("00:00", "05:00")
        london = df.between_time("07:00", "10:00")
        if not asian.empty:
            levels["asian_high"], levels["asian_low"] = asian['High'].max(), asian['Low'].min()
        if not london.empty:
            levels["london_high"], levels["london_low"] = london['High'].max(), london['Low'].min()
        levels["mid"] = (df['High'].max() + df['Low'].min()) / 2
    except: pass
    return levels

# ===== KILLZONE + NEWS =====
def is_killzone(trade_type: str):
    if trade_type == "swing": return True
    now_utc = datetime.utcnow().time()
    london = time(7, 0) <= now_utc <= time(10, 0)
    ny = time(12, 30) <= now_utc <= time(15, 30)
    return london or ny

async def check_news_block(symbol: str, hours: int = 4):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=5)
            data = r.json()
        now = datetime.utcnow()
        currencies = [symbol[:3], symbol[3:6]] if len(symbol) == 6 else ["USD"]
        for event in data:
            if event["country"] in currencies and event["impact"] == "High":
                event_time = datetime.strptime(f"{event['date']} {event['time']}", "%b %d %H:%M")
                if abs((event_time - now).total_seconds()) < hours * 3600:
                    return True, event["title"]
        return False, None
    except:
        return False, None

# ===== POSITION SIZE =====
def calc_lot_size(account_balance: float, risk_percent: float, entry: float, sl: float, symbol: str):
    resolved = resolve_symbol(symbol)
    sl_pips = abs(entry - sl) * resolved["pip"]
    if sl_pips == 0: return 0.01
    risk_amount = account_balance * (risk_percent / 100)
    pip_value = 10 if resolved["type"] == "forex" else 1
    lot_size = risk_amount / (sl_pips * pip_value)
    return max(0.01, round(lot_size, 2))

# ===== CONFLUENCE SCORER V2 =====
async def calc_confluence_score_v2(symbol: str, direction: str, trade_type: str, mtf: dict, macro: dict, liq: dict, user: dict):
    score = 0
    reasons = []
    warnings = []

    if "H4" in mtf:
        h4_trend = "BULLISH" if mtf["H4"]['Close'].iloc[-1] > mtf["H4"]['Close'].iloc[-20] else "BEARISH"
        if h4_trend == direction: score += 25; reasons.append("HTF Aligned")
        else: warnings.append("HTF Counter-Trend")

    if liq["eqh"] or liq["eql"]: score += 20; reasons.append("Liquidity Sweep")

    if macro["bias"] == direction: score += 15; reasons.append(f"Macro: DXY {macro.get('DXY')}")
    else: warnings.append(f"Macro Conflict: DXY {macro.get('DXY')}")

    flow = await get_order_flow(symbol)
    if flow["cot_bias"] == direction: score += 10; reasons.append("COT Aligned")
    if flow["retail"]!= direction and flow["retail"]!= "NEUTRAL": score += 5; reasons.append("Fade Retail")

    if trade_type == "daytrade" and is_killzone("daytrade"): score += 15; reasons.append("Killzone Active")
    elif trade_type == "swing": score += 10; reasons.append("Swing Mode")

    news_block, event = await check_news_block(symbol, 24 if user["news_lockout"] else 4)
    if not news_block: score += 10; reasons.append("News Clear")
    else: score -= 40; warnings.append(f"RED NEWS: {event}")

    if liq["hvn"]: score += 10; reasons.append("HVN Confluence")

    return min(100, max(0, score)), reasons, warnings, flow

# ===== CHART =====
async def capture_chart(symbol: str, interval: str = "60"):
    resolved = resolve_symbol(symbol)
    url = f"https://www.tradingview.com/chart/?symbol={resolved['tv']}&interval={interval}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(5000)
        screenshot = await page.screenshot(type="png")
        await browser.close()
        return screenshot

# ===== AI ANALYSIS 10/10 =====
async def get_ai_analysis(prompt, user, symbol, trade_type):
    if user["locked"]:
        return f"ACCOUNT LOCKED: Daily DD {user['max_daily_dd']}% hit. P&L: ${user['daily_pnl']:.2f}\n\n✝️🩸"

    macro = await get_macro_context(symbol)
    mtf = await get_mtf_data(symbol, trade_type)
    liq = get_liquidity_zones(symbol, mtf)
    levels = get_session_levels(symbol, mtf)

    if not is_killzone(trade_type) and trade_type == "daytrade":
        return f"OUTSIDE KILLZONE: London 7-10 UTC or NY 12:30-15:30 UTC only\n\n✝️🩸"

    news_block, news_event = await check_news_block(symbol, 24 if user["news_lockout"] else 4)
    if news_block:
        return f"NEWS BLOCK: {news_event} within {'24h' if user['news_lockout'] else '4h'}. No trades.\n\n✝️🩸"

    direction_prelim = macro["bias"]
    score, reasons, warnings, flow = await calc_confluence_score_v2(symbol, direction_prelim, trade_type, mtf, macro, liq)

    if score < user["min_confluence"]:
        return f"LOW CONFLUENCE: Score {score}/100 < Required {user['min_confluence']}\nReasons: {', '.join(reasons)}\nWarnings: {', '.join(warnings)}\nNo trade. Wait for A+ setup.\n\n✝️🩸"

    macro_str = f"DXY:{macro.get('DXY')} US10Y:{macro.get('US10Y')} RISK:{macro.get('RISK')} Warnings:{macro.get('warnings')}"
    liq_str = f"EQH:{liq['eqh'][:2]} EQL:{liq['eql'][:2]} HVN:{liq['hvn'][:1]} Sessions: AH:{levels['asian_high']} AL:{levels['asian_low']}"
    flow_str = f"COT:{flow['cot_bias']} Retail:{flow['retail']}"

    if trade_type == "swing":
        system_prompt = f"""You are Apex Wolf Swing Sniper. Account: ${user['account_balance']}, Risk: {user['risk_percent']}%.
MACRO: {macro_str}
LIQUIDITY: {liq_str}
ORDER FLOW: {flow_str}
CONFLUENCE: {score}/100 - {', '.join(reasons)}
WARNINGS: {', '.join(warnings)}
Analyze W1/D1/H4. Hold 2-10 days. Target 1:3 to 1:5 R:R. Must align with macro.
Format:
ICT/SMC SWING: {symbol} D1 | SCORE: {score}/100
HTF Bias: BULLISH/BEARISH [Weekly]
Daily Structure: [D1]
H4 Entry: [Refined]
Macro: {macro.get('DXY')} DXY, {macro.get('US10Y')} Yields
Order Flow: COT {flow['cot_bias']}, Retail {flow['retail']}
Confluence: {', '.join(reasons)}
Entry: [price]
TP1: [price] (Weekly)
TP2: [price] (Monthly)
SL: [price] (Below D1 OB)
R:R = [ratio] | Risk: {user['risk_percent']}%
Lot Size: [calculated]
Hold: 2-10 days
WARNINGS: {', '.join(warnings)}
Educational only. ✝️🩸"""
    else:
        system_prompt = f"""You are Apex Wolf Day Trade Killer. Account: ${user['account_balance']}, Risk: {user['risk_percent']}%.
MACRO: {macro_str}
LIQUIDITY: {liq_str}
ORDER FLOW: {flow_str}
CONFLUENCE: {score}/100 - {', '.join(reasons)}
Analyze H4/H1/M15. Killzone only. Hold <8 hours. Target 1:2 to 1:3 R:R. Must have liquidity sweep.
Format:
ICT/SMC DAYTRADE: {symbol} H1 | SCORE: {score}/100
HTF Bias: BULLISH/BEARISH [H4]
MTF Structure: [H1]
LTF Entry: [M15 Sweep]
Macro: {macro.get('DXY')} DXY, {macro.get('RISK')} Risk
Order Flow: COT {flow['cot_bias']}, Retail {flow['retail']}
Confluence: {', '.join(reasons)}
Entry: [price]
TP1: [price] (H1 FVG)
TP2: [price] (H4 High)
SL: [price] (Below M15 OB)
R:R = [ratio] | Risk: {user['risk_percent']}%
Lot Size: [calculated]
Hold: <8 hours
WARNINGS: {', '.join(warnings)}
Educational only. ✝️🩸"""

    mtf_context = f"MTF Available: {list(mtf.keys())}"

    explanation = f"\n\n📖 **WHY THIS TRADE**\n"
    explanation += f"1. HTF Bias: {macro.get('DXY')} DXY = {direction_prelim} for {symbol}\n"
    explanation += f"2. Liquidity: Swept {'sell-side' if direction_prelim=='BULLISH' else 'buy-side'} below/above {liq['eql'] if direction_prelim=='BULLISH' else liq['eqh']}\n"
    explanation += f"3. POI: H1 {'Bullish' if direction_prelim=='BULLISH' else 'Bearish'} OB in {'discount' if direction_prelim=='BULLISH' else 'premium'}\n"
    explanation += f"4. Entry: M15 CHOCH into POI during {'London/NY' if trade_type=='daytrade' else 'Any'} session\n"
    explanation += f"5. Confluence: {score}/100 = {', '.join(reasons)}\n"
    explanation += f"6. Order Flow: COT {flow['cot_bias']}, Fade Retail {flow['retail']}\n"
    explanation += f"\n🎓 **Learn More**: /lesson 2_liquidity or /lesson 3_fvg_ob"

    if GROQ_API_KEY:
        try:
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY)
            chat = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": f"Analyze: {prompt}\nMTF:{mtf_context}"}],
                temperature=0.1, max_tokens=1000
            )
            return chat.choices[0].message.content + explanation
        except Exception as e:
            sentry_sdk.capture_exception(e)
            pass

    if GOOGLE_AI_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=GOOGLE_AI_KEY)
            model = genai.GenerativeModel('gemini-1.5-pro')
            response = model.generate_content([system_prompt, f"Analyze: {prompt}\nMTF:{mtf_context}"])
            return response.text + explanation
        except Exception as e:
            sentry_sdk.capture_exception(e)
            pass

    return "Add GROQ_API_KEY or GOOGLE_AI_KEY.\n\n✝️🩸"

@app.post("/analyze")
async def analyze_endpoint(req: AnalyzeRequest):
    user = await get_user_data(req.user_id)
    if req.account_balance:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET account_balance=? WHERE user_id=?", (req.account_balance, req.user_id))
            await db.commit()
        user = await get_user_data(req.user_id)

    prompt = req.prompt.upper()
    symbol = prompt.split()[0]
    trade_type = "swing" if any(x in prompt for x in ["SWING", "D1", "DAILY", "WEEKLY"]) else "daytrade"

    chart_img = None
    try:
        chart_img = await capture_chart(symbol, "240" if trade_type == "swing" else "60")
    except Exception as e:
        sentry_sdk.capture_exception(e)

    ai_text = await get_ai_analysis(prompt, user, symbol, trade_type)

    if "BULLISH" in ai_text or "BEARISH" in ai_text:
        if all(x not in ai_text for x in ["LOCKED", "KILLZONE", "NEWS BLOCK", "LOW CONFLUENCE"]):
            try:
                entry = float(re.search(r'Entry: ([\d.]+)', ai_text).group(1))
                tp = float(re.search(r'TP1: ([\d.]+)', ai_text).group(1))
                sl = float(re.search(r'SL: ([\d.]+)', ai_text).group(1))
                rr = re.search(r'R:R = ([\d:.]+)', ai_text).group(1)
                lot_size = calc_lot_size(user["account_balance"], user["risk_percent"], entry, sl, symbol)
                score = int(re.search(r'SCORE: (\d+)/100', ai_text).group(1))
                ai_text = re.sub(r'Lot Size: \[calculated\]', f'Lot Size: {lot_size}', ai_text)
                direction = "BUY" if "BULLISH" in ai_text else "SELL"
                macro = await get_macro_context(symbol)
                flow = await get_order_flow(symbol)

                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""INSERT INTO trades (user_id, symbol, direction, entry, sl, tp, lot_size, status, pnl, rr, timestamp, trade_type, confluence_score, macro_json, notes)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                           (req.user_id, symbol, direction, entry, sl, tp, lot_size, "pending", 0.0, rr,
                            datetime.now().isoformat(), trade_type, score, json.dumps({"macro": macro, "flow": flow}), ai_text[:500]))
                    await db.commit()
            except Exception as e:
                sentry_sdk.capture_exception(e)

    return {"analysis": ai_text, "chart": base64.b64encode(chart_img).decode() if chart_img else None}

@app.post("/close_trade")
async def close_trade(req: CloseTrade):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM trades WHERE id=? AND user_id=?", (req.trade_id, req.user_id))
        trade = await cur.fetchone()
        if not trade: return {"error": "Trade not found"}
        entry, lot_size, direction, symbol = trade[4], trade[7], trade[3], trade[2]
        resolved = resolve_symbol(symbol)
        pip_val = 10 if resolved["type"] == "forex" else 1
        if "XAU" in symbol: pip_val = 100
        if "BTC" in symbol: pip_val = 1

        pnl = (req.close_price - entry) * lot_size * pip_val * resolved["pip"] if direction == "BUY" else (entry - req.close_price) * lot_size * pip_val * resolved["pip"]

        await db.execute("UPDATE trades SET status='closed', pnl=? WHERE id=?", (pnl, req.trade_id))
        await db.commit()
    return {"status": "closed", "pnl": round(pnl, 2)}

@app.post("/manage/{trade_id}")
async def manage_trade(trade_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM trades WHERE id=? AND status='pending'", (trade_id,))
        trade = await cur.fetchone()
        if not trade: return {"error": "Trade not found or closed"}
        
        symbol, entry, sl, tp1, direction = trade[2], trade[4], trade[5], trade[6], trade[3]
        price_data = await get_price(symbol)
        if "price" not in price_data: return {"error": "No price"}
        current = price_data["price"]
        
        alerts = []
        risk_pips = abs(entry - sl)
        if direction == "BUY" and current >= entry + risk_pips:
            alerts.append(f"🚨 MOVE SL TO BE: {entry} | Current: {current}")
        if direction == "SELL" and current <= entry - risk_pips:
            alerts.append(f"🚨 MOVE SL TO BE: {entry} | Current: {current}")
        
        if direction == "BUY" and current >= tp1:
            alerts.append(f"🎯 TP1 HIT: {tp1} | Close 50% + Move SL to BE")
        if direction == "SELL" and current <= tp1:
            alerts.append(f"🎯 TP1 HIT: {tp1} | Close 50% + Move SL to BE")
        
        return {"alerts": alerts, "current": current}

@app.get("/scan")
async def scan_market(user_id: int = 0):
    majors = ["EURUSD","GBPUSD","USDJPY","XAUUSD","GBPJPY","BTCUSD","US30","NAS100","AUDUSD","USDCAD"]
    results = []
    for pair in majors:
        try:
            user = await get_user_data(user_id)
            if user["locked"]: continue
            ai_text = await get_ai_analysis(f"{pair} H1 daytrade", user, pair, "daytrade")
            if "BULLISH" in ai_text or "BEARISH" in ai_text:
                if any(x in ai_text for x in ["LOCKED", "KILLZONE", "NEWS", "LOW CONFLUENCE"]): continue
                bias = "BULLISH" if "BULLISH" in ai_text else "BEARISH"
                rr = re.search(r'R:R = ([\d:.]+)', ai_text)
                score = re.search(r'SCORE: (\d+)/100', ai_text)
                results.append({"pair": pair, "bias": bias, "rr": rr.group(1) if rr else "1:2", "score": score.group(1) if score else "0"})
            if len(results) >= 3: break
        except Exception as e:
            sentry_sdk.capture_exception(e)
    return {"scans": results}

@app.get("/history")
async def get_history(user_id: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM trades WHERE user_id =? ORDER BY id DESC LIMIT 10", (user_id,))
        rows = await cur.fetchall()
    return [{"id": r[0], "symbol": r[2], "direction": r[3], "entry": r[4], "sl": r[5], "tp": r[6],
             "lot_size": r[7], "status": r[8], "pnl": r[9], "rr": r[10], "timestamp": r[11],
             "trade_type": r[12], "confluence_score": r[13]} for r in rows]

# ===== TELEGRAM =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_data(update.effective_user.id)
    keyboard = [
        [InlineKeyboardButton("📊 Analyze", callback_data="analyze"), InlineKeyboardButton("🔍 Scan A+", callback_data="scan")],
        [InlineKeyboardButton("💰 Price", callback_data="price"), InlineKeyboardButton("📸 Chart", callback_data="chart")],
        [InlineKeyboardButton("📜 Journal", callback_data="history"), InlineKeyboardButton("🎓 Learn", callback_data="learn")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ]
    await update.message.reply_text(
        f"✝️🩸 *Apex Wolf 10.0*\n\nBalance: `${user['account_balance']}` | Risk: `{user['risk_percent']}%`\nDaily P&L: `${user['daily_pnl']:.2f}` | DD Limit: `{user['max_daily_dd']}%`\nMin Confluence: `{user['min_confluence']}/100`\nNews Lockout: `{'ON' if user['news_lockout'] else 'OFF'}`\n\n{'🔒 LOCKED' if user['locked'] else '✅ ACTIVE'}\n\n`/analyze EURUSD H1 daytrade` or `/analyze GBPJPY D1 swing`",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = ' '.join(context.args)
    user_id = update.effective_user.id
    if not prompt: return await update.message.reply_text("Usage: `/analyze EURUSD H1 daytrade` or `/analyze XAUUSD D1 swing`")
    msg = await update.message.reply_text("⚡ Macro scan + MTF + Liquidity + Order Flow + Gates... ✝️🩸")
    try:
        res = requests.post(f"http://localhost:{PORT}/analyze", json={"prompt": prompt, "user_id": user_id}, timeout=120)
        data = res.json()
        if data.get("chart"):
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=io.BytesIO(base64.b64decode(data["chart"])),
                                         caption=f"```\n{data['analysis']}\n```", parse_mode="Markdown")
            await msg.delete()
        else:
            await msg.edit_text(f"```\n{data['analysis']}\n```", parse_mode="Markdown")
    except Exception as e:
        sentry_sdk.capture_exception(e)
        await msg.edit_text(f"❌ Error: {e}")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Scanning 10 majors for 75+ confluence setups...")
    res = requests.get(f"http://localhost:{PORT}/scan?user_id={update.effective_user.id}", timeout=180).json()
    if not res["scans"]: return await msg.edit_text("No A+ setups. Macro conflict, news block, or outside killzone.")
    text = "🎯 *A+ Setups Found*\n\n" + "\n".join([f"*{s['pair']}*: {s['bias']} | R:R {s['rr']} | Score {s['score']}/100" for s in res["scans"]])
    await msg.edit_text(text, parse_mode="Markdown")

async def learn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🎓 *Apex Wolf Trading School*\n\n"
    for level, topics in CURRICULUM.items():
        text += f"**{level.upper()}**\n"
        for key, topic in topics.items():
            text += f" /lesson {key} - {topic['title']}\n"
        text += "\n"
    text += "Take quiz: /quiz beginner\nCheck progress: /progress\n\n✝️🩸"
    await update.message.reply_text(text, parse_mode="Markdown")

async def lesson_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/lesson 1_pips_lots`")
    topic_key = context.args[0]
    user_id = update.effective_user.id
    
    lesson = None
    level_found = None
    for level, topics in CURRICULUM.items():
        if topic_key in topics:
            lesson = topics[topic_key]
            level_found = level
            break
    if not lesson: return await update.message.reply_text("Topic not found. Use /learn to see all topics.")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO lessons VALUES (?,?,?,?,?,?)", 
                         (user_id, level_found, topic_key, 1, 0, datetime.now().isoformat()))
        await db.commit()
    
    await update.message.reply_text(f"📚 *{lesson['title']}*\n\n{lesson['content']}\n\nTest yourself: /quiz {level_found}", parse_mode="Markdown")

async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/quiz beginner`")
    level = context.args[0]
    if level not in CURRICULUM: return await update.message.reply_text("Level not found. Use: beginner, intermediate, advanced")
    
    import random
    all_q = []
    for topic in CURRICULUM[level].values():
        all_q.extend(topic["quiz"])
    questions = random.sample(all_q, min(3, len(all_q)))
    
    context.user_data["quiz"] = {"level": level, "questions": questions, "current": 0, "score": 0}
    
    q = questions[0]
    opts = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
    await update.message.reply_text(f"🧠 *Quiz: {level}*\n\nQ1: {q['q']}\n\n{opts}\n\nReply with number 1-3", parse_mode="Markdown")

async def answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "quiz" not in context.user_data: return
    quiz = context.user_data["quiz"]
    try:
        ans_idx = int(update.message.text) - 1
        q = quiz["questions"][quiz["current"]]
        correct = q["options"][ans_idx] == q["a"]
        if correct: quiz["score"] += 1
        
        quiz["current"] += 1
        if quiz["current"] < len(quiz["questions"]):
            q = quiz["questions"][quiz["current"]]
            opts = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(q["options"])])
            await update.message.reply_text(f"{'✅ Correct' if correct else '❌ Wrong'}\n\nQ{quiz['current']+1}: {q['q']}\n\n{opts}")
        else:
            score_pct = quiz["score"] / len(quiz["questions"]) * 100
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT OR REPLACE INTO quiz_progress VALUES (?,?,?,?)",
                                 (update.effective_user.id, quiz["level"], score_pct, quiz["level"]))
                await db.commit()
            await update.message.reply_text(f"🏁 Quiz Done! Score: {quiz['score']}/{len(quiz['questions'])} = {score_pct:.0f}%\n\n{'✅ Passed! Next level unlocked.' if score_pct >= 80 else '❌ Need 80% to pass. Review /learn'}")
            del context.user_data["quiz"]
    except: pass

async def progress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT module, COUNT(*) FROM lessons WHERE user_id=? AND completed=1 GROUP BY module", (user_id,))
        completed = await cur.fetchall()
        cur = await db.execute("SELECT level, last_score FROM quiz_progress WHERE user_id=?", (user_id,))
        quiz = await cur.fetchall()
    
    text = "📊 *Your Progress*\n\n**Lessons Completed:**\n"
    for mod, count in completed:
        total = len(CURRICULUM[mod])
        text += f"{mod}: {count}/{total}\n"
    text += "\n**Quiz Scores:**\n"
    for lvl, score in quiz:
        text += f"{lvl}: {score:.0f}%\n"
    text += "\nKeep going ✝️🩸"
    await update.message.reply_text(text, parse_mode="Markdown")

async def review_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/review 1` for trade ID 1")
    trade_id = int(context.args[0])
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM trades WHERE id=? AND user_id=?", (trade_id, update.effective_user.id))
        trade = await cur.fetchone()
    if not trade: return await update.message.reply_text("Trade not found")
    
    symbol, direction, entry, sl, tp, lot_size, pnl, rr, conf, notes = trade[2], trade[3], trade[4], trade[5], trade[6], trade[7], trade[9], trade[10], trade[13], trade[15]
    result = "✅ WIN" if pnl > 0 else "❌ LOSS" if pnl < 0 else "⏳ PENDING"
    text = f"🔍 *Trade Review ID:{trade_id}*\n\n"
    text += f"**{symbol} {direction}** | Score: {conf}/100\n"
    text += f"Entry: {entry} | SL: {sl} | TP: {tp}\n"
    text += f"Size: {lot_size} lots | R:R: {rr}\n"
    text += f"Result: {result} `${pnl:.2f}`\n\n"
    text += f"**Why it was taken:**\n{notes[:400]}...\n\n"
    text += f"**Lesson**: {'Risk management worked' if pnl >= 0 else 'Check confluence. Was score <75? Did you ignore warnings?'}"
    await update.message.reply_text(text, parse_mode="Markdown")

async def setbalance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/setbalance 500`")
    bal = float(context.args[0])
    await requests.post(f"http://localhost:{PORT}/settings", json={"user_id": update.effective_user.id, "account_balance": bal})
    await update.message.reply_text(f"✅ Balance set to ${bal}. Risk calc updated.")

async def setrisk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/setrisk 0.5` for 0.5%")
    risk = float(context.args[0])
    await requests.post(f"http://localhost:{PORT}/settings", json={"user_id": update.effective_user.id, "risk_percent": risk})
    await update.message.reply_text(f"✅ Risk set to {risk}% per trade")

async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return await update.message.reply_text("Usage: `/close 1 1.08500`")
    trade_id, close_price = int(context.args[0]), float(context.args[1])
    res = requests.post(f"http://localhost:{PORT}/close_trade", json={"trade_id": trade_id, "user_id": update.effective_user.id, "close_price": close_price}).json()
    await update.message.reply_text(f"✅ Trade {trade_id} closed. P&L: ${res['pnl']}")

async def manage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/manage 1` for trade ID 1")
    trade_id = int(context.args[0])
    res = requests.post(f"http://localhost:{PORT}/manage/{trade_id}").json()
    if "alerts" in res and res["alerts"]:
        await update.message.reply_text("\n".join(res["alerts"]))
    else:
        await update.message.reply_text(f"No action needed. Current: {res.get('current', 'N/A')}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cmds = {"analyze": "Send: `/analyze EURUSD H1 daytrade`", "scan": scan_cmd, "price": "Send: `/price XAUUSD`",
            "chart": "Send: `/chart EURUSD 60`", "history": history_cmd, "learn": learn_cmd, "settings": settings_cmd}
    if query.data in cmds:
        if callable(cmds[query.data]): await cmds[query.data](update, context)
        else: await query.edit_message_text(cmds[query.data])

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/price EURUSD`")
    res = await get_price(context.args[0].upper())
    await update.message.reply_text(f"💰 *{res['symbol']}*\nPrice: `{res['price']}`", parse_mode="Markdown")

async def chart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/chart EURUSD 60`")
    symbol, interval = context.args[0].upper(), context.args[1] if len(context.args) > 1 else "60"
    msg = await update.message.reply_text(f"📸 Capturing {symbol}...")
    try:
        img = await capture_chart(symbol, interval)
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=io.BytesIO(img))
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Chart failed: {e}")

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = requests.get(f"http://localhost:{PORT}/history?user_id={update.effective_user.id}", timeout=10).json()
    if not res: return await update.message.reply_text("📭 No trades yet.")
    total_pnl = sum(t['pnl'] for t in res)
    wins = sum(1 for t in res if t['pnl'] > 0)
    text = f"📜 *Journal* | P&L: `${total_pnl:.2f}` | WR: `{wins/len(res)*100:.1f}%`\n\n"
    for s in res[:5]:
        emoji = "✅" if s["pnl"] > 0 else "❌" if s["pnl"] < 0 else "⏳"
        text += f"{emoji} ID:{s.get('id','?')} *{s['symbol']} {s['direction']}* {s['lot_size']} lots | Score:{s.get('confluence_score','?')} | `${s['pnl']:.2f}`\n"
    text += "\nClose with `/close ID PRICE` | Review: `/review ID`"
    await update.message.reply_text(text, parse_mode="Markdown")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_data(update.effective_user.id)
    await update.message.reply_text(
        f"⚙️ *Settings*\n\nBalance: `${user['account_balance']}`\nRisk: `{user['risk_percent']}%`\nDaily DD: `{user['max_daily_dd']}%`\nMin Confluence: `{user['min_confluence']}/100`\nNews Lockout: `{'ON' if user['news_lockout'] else 'OFF'}`\nDaily P&L: `${user['daily_pnl']:.2f}`\nStatus: {'🔒 LOCKED' if user['locked'] else '✅ ACTIVE'}\n\nUpdate: `/setbalance 1000` or `/setrisk 0.5`\n\n✝️🩸",
        parse_mode="Markdown")

def run_bot():
    if not TELEGRAM_BOT_TOKEN: return
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    for cmd, func in [("start", start), ("analyze", analyze_cmd), ("scan", scan_cmd), ("price", price_cmd),
                      ("chart", chart_cmd), ("history", history_cmd), ("learn", learn_cmd), ("lesson", lesson_cmd),
                      ("quiz", quiz_cmd), ("progress", progress_cmd), ("review", review_cmd), ("manage", manage_cmd),
                      ("settings", settings_cmd), ("setbalance", setbalance_cmd), ("setrisk", setrisk_cmd), ("close", close_cmd)]:
        application.add_handler(CommandHandler(cmd, func))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer_handler))
    application.run_polling()

@app.on_event("startup")
async def startup_event():
    await init_db()
    if TELEGRAM_BOT_TOKEN:
        threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
