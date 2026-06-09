import os
import asyncio
import threading
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIG =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
DEMO_ACCOUNT = "#436233200"
RISK = "0.25%"

# ===== FASTAPI BACKEND =====
app = FastAPI(title="Apex Wolf AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    prompt: str

class HistoryItem(BaseModel):
    symbol: str
    direction: str
    entry: float
    tp: float
    sl: float
    status: str
    timestamp: str

# Mock DB - replace with real logic later
SIGNAL_HISTORY = [
    {
        "symbol": "EURUSD", "direction": "BUY", "entry": 1.08450, "tp": 1.08900, 
        "sl": 1.08200, "status": "win", "timestamp": "2026-01-15 14:30"
    },
    {
        "symbol": "XAUUSD", "direction": "SELL", "entry": 2045.50, "tp": 2035.00, 
        "sl": 2050.00, "status": "win", "timestamp": "2026-01-15 10:15"
    }
]

@app.get("/")
def root():
    return {"status": "Apex Wolf Backend Online ✝️🩸", "account": DEMO_ACCOUNT}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyze")
def analyze_endpoint(req: AnalyzeRequest):
    # YOUR ACTUAL AI LOGIC GOES HERE
    # This is mock response matching your frontend structure
    prompt = req.prompt.upper()
    
    if "EURUSD" in prompt:
        analysis = f"""
ICT ANALYSIS: {prompt}
Direction: BULLISH BIAS
Entry: 1.08450 - 1.08500 OB
TP1: 1.08900 (Daily FVG)
TP2: 1.09200 (Weekly High)
SL: 1.08200 (Below 1H OB)

R:R = 1:2.5 | Risk: {RISK}
Account: {DEMO_ACCOUNT}

✝️🩸 Educational only. Not financial advice.
"""
    elif "XAUUSD" in prompt or "GOLD" in prompt:
        analysis = f"""
SMC ANALYSIS: {prompt}
Direction: BEARISH BIAS 
Entry: 2045.50 - 2047.00 Supply
TP1: 2035.00 (4H Demand)
SL: 2050.00 (Above Supply)

Liquidity Sweep: Asian High
R:R = 1:2.1 | Risk: {RISK}
Account: {DEMO_ACCOUNT}

✝️🩸 Educational only. Not financial advice.
"""
    else:
        analysis = f"""
MARKET SCAN: {prompt}
No clear setup detected. 
Wait for NY killzone or London sweep.
Risk: {RISK} | Account: {DEMO_ACCOUNT}

✝️🩸 Educational only. Not financial advice.
"""
    
    return {"analysis": analysis.strip(), "account": DEMO_ACCOUNT, "risk": RISK}

@app.get("/history")
def get_history():
    return SIGNAL_HISTORY

# ===== TELEGRAM BOT =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Analyze Market", callback_data="analyze")],
        [InlineKeyboardButton("📜 History", callback_data="history"), InlineKeyboardButton("⚙️ Settings", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✝️🩸 *Chart AI Pro*\n\n"
        f"Demo: `{DEMO_ACCOUNT}` | Risk: `{RISK}`\n\n"
        f"Send `/analyze EURUSD H1` or use buttons below:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = ' '.join(context.args)
    if not prompt:
        await update.message.reply_text(
            "Usage: `/analyze EURUSD H1 with ICT`\n\n"
            "Examples:\n"
            "• `/analyze XAUUSD`\n"
            "• `/analyze BTCUSD 15m FVG`\n"
            "• `/analyze GBPJPY NY session`",
            parse_mode="Markdown"
        )
        return
    
    msg = await update.message.reply_text("⚡ Analyzing market structure... ✝️🩸")
    
    try:
        # Call our own FastAPI endpoint
        res = requests.post(
            f"http://localhost:{PORT}/analyze", 
            json={"prompt": prompt}, 
            timeout=30
        )
        data = res.json()
        await msg.edit_text(f"```\n{data['analysis']}\n```", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Backend Error: {e}\n\nCheck if bot is running.")

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        res = requests.get(f"http://localhost:{PORT}/history", timeout=10)
        signals = res.json()
        
        if not signals:
            await update.message.reply_text("📭 No signals yet. Run `/analyze` first.")
            return
        
        text = "📜 *Signal History*\n\n"
        for s in signals[-5:]: # Last 5
            emoji = "✅" if s["status"] == "win" else "❌"
            text += f"{emoji} *{s['symbol']} {s['direction']}*\n"
            text += f"Entry: `{s['entry']}` | TP: `{s['tp']}` | SL: `{s['sl']}`\n"
            text += f"Status: {s['status'].upper()} | {s['timestamp']}\n\n"
        
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"""
⚙️ *Settings*

*Account:* `{DEMO_ACCOUNT}`
*Risk Per Trade:* `{RISK}`
*Max Daily Loss:* `1.00%`
*Strategy:* `ICT / SMC`

⚠️ *Disclaimer*
Educational code only. Not financial advice. 
Trading involves risk of loss.

✝️🩸
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "analyze":
        await query.edit_message_text("Send: `/analyze EURUSD H1`")
    elif query.data == "history":
        await history_cmd(update, context)
    elif query.data == "settings":
        await settings_cmd(update, context)

def run_bot():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set. Bot disabled.")
        return
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("analyze", analyze_cmd))
    application.add_handler(CommandHandler("history", history_cmd))
    application.add_handler(CommandHandler("settings", settings_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))
    
    from telegram.ext import CallbackQueryHandler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 Telegram bot starting...")
    application.run_polling()

# Start bot in background thread when FastAPI starts
@app.on_event("startup")
async def startup_event():
    if TELEGRAM_BOT_TOKEN:
        thread = threading.Thread(target=run_bot, daemon=True)
        thread.start()
        print("✅ Bot thread started")
    else:
        print("⚠️ TELEGRAM_BOT_TOKEN missing - bot disabled")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
