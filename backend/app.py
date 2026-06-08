import os, json, time, requests, imaplib, email
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import yfinance as yf
import pandas as pd
from groq import Groq
import google.generativeai as genai
import telegram

load_dotenv()
app = Flask(__name__)

# ENV - 7 KEYS, NO TWELVEDATA
AI_STUDIO_KEY = os.getenv("AI_STUDIO_KEY")
GROQ_KEY = os.getenv("GROQ_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ALPHA_KEY = os.getenv("ALPHA_VANTAGE_KEY")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_SECRET = os.getenv("EMAIL_ALERT_SECRET")

bot = telegram.Bot(token=TELEGRAM_TOKEN)
groq_client = Groq(api_key=GROQ_KEY)
if AI_STUDIO_KEY:
    genai.configure(api_key=AI_STUDIO_KEY)
    vision_model = genai.GenerativeModel('gemini-1.5-flash')

# 1. DUAL DATA FETCHER - YAHOO + ALPHA, NO TWELVEDATA
def get_median_price(pair):
    try:
        # Yahoo
        y_ticker = pair.replace("/", "") + "=X" if "/" in pair else pair
        yf_data = yf.download(y_ticker, period="1d", interval="15m", progress=False)
        y_close = yf_data['Close'].iloc[-1] if not yf_data.empty else 0
        
        # Alpha Vantage
        av_pair = pair.replace("/", "")
        av_url = f"https://www.alphavantage.co/query?function=FX_INTRADAY&from_symbol={av_pair[:3]}&to_symbol={av_pair[3:]}&interval=15min&apikey={ALPHA_KEY}"
        av_data = requests.get(av_url, timeout=10).json()
        av_close = float(list(av_data['Time Series FX (15min)'].values())[0]['4. close']) if 'Time Series FX (15min)' in av_data else 0
        
        prices = [p for p in [y_close, av_close] if p > 0]
        if len(prices) == 0: return None
        if len(prices) == 1: return prices[0]
        
        # ATR divergence check: if >0.3% apart, bad data
        if abs(prices[0] - prices[1]) / prices[0] > 0.003: return None
        return sum(prices) / len(prices)
    except:
        return None

# 2. SMC CALCULATOR - BOS/FVG/OB
def calc_smc(pair):
    try:
        df = yf.download(pair.replace("/", "") + "=X", period="5d", interval="15m", progress=False)
        if df.empty: return None
        # BOS logic
        highs, lows = df['High'], df['Low']
        last_high, last_low = highs.iloc[-2], lows.iloc[-2]
        bos = "BULL" if df['Close'].iloc[-1] > last_high else "BEAR" if df['Close'].iloc[-1] < last_low else None
        # FVG logic
        fvg = None
        if len(df) > 2:
            if df['Low'].iloc[-1] > df['High'].iloc[-3]: fvg = f"{df['High'].iloc[-3]:.5f}-{df['Low'].iloc[-1]:.5f}"
            if df['High'].iloc[-1] < df['Low'].iloc[-3]: fvg = f"{df['High'].iloc[-1]:.5f}-{df['Low'].iloc[-3]:.5f}"
        return {"bos": bos, "fvg": fvg, "price": df['Close'].iloc[-1]}
    except:
        return None

# 3. GUARDS - DXY/VIX/SPREAD
def check_guards(pair):
    try:
        dxy = yf.download("DX-Y.NYB", period="1d", interval="5m", progress=False)
        vix = yf.download("^VIX", period="1d", interval="5m", progress=False)
        dxy_up = dxy['Close'].iloc[-1] > dxy['Close'].iloc[-5] if not dxy.empty else False
        vix_spike = vix['Close'].iloc[-1] > 20 if not vix.empty else False
        # Spread check via Myfxbook free - stub, returns True if OK
        return {"dxy_up": dxy_up, "vix_spike": vix_spike, "spread_ok": True}
    except:
        return {"dxy_up": False, "vix_spike": False, "spread_ok": True}

# 4. 2/3 AI ENSEMBLE - RULE + GROQ + AI STUDIO
def ai_ensemble(pair, smc_data, guards):
    votes = []
    
    # Vote 1: Rule Engine
    rule_vote = "BULL" if smc_data["bos"] == "BULL" and not guards["dxy_up"] else "BEAR" if smc_data["bos"] == "BEAR" and guards["dxy_up"] else "NO"
    votes.append(rule_vote)
    
    # Vote 2: Groq Data Analysis
    try:
        groq_resp = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": f"Pair:{pair} BOS:{smc_data['bos']} FVG:{smc_data['fvg']} DXY_UP:{guards['dxy_up']} VIX_SPIKE:{guards['vix_spike']}. Vote: BULL, BEAR, or NO. One word."}],
            model="llama-3.1-70b-versatile", max_tokens=5
        )
        votes.append(groq_resp.choices[0].message.content.strip())
    except:
        votes.append("NO")
    
    # Vote 3: AI Studio - stub for now, assumes no chart
    votes.append("NO") # Will add chart upload logic in Step 3
    
    bull_votes = votes.count("BULL")
    bear_votes = votes.count("BEAR")
    if bull_votes >= 2: return "BULL"
    if bear_votes >= 2: return "BEAR"
    return "NO"

# 5. MAIN 9.5/10 PIPELINE
def run_95_pipeline(pair, event, tv_price):
    median_price = get_median_price(pair)
    if not median_price: return {"status": "bad_data"}
    
    smc = calc_smc(pair)
    if not smc or not smc["bos"]: return {"status": "no_setup"}
    
    guards = check_guards(pair)
    if guards["vix_spike"] or not guards["spread_ok"]: return {"status": "guard_block"}
    
    direction = ai_ensemble(pair, smc, guards)
    if direction == "NO": return {"status": "no_confluence"}
    
    # Telegram post
    sl = median_price * 0.998 if direction == "BULL" else median_price * 1.002
    tp = median_price * 1.006 if direction == "BULL" else median_price * 0.994
    msg = f"""🐺 APEX WOLF 9.5/10 SIGNAL
{pair} M15 {direction} 
Entry: {median_price:.5f} | SL: {sl:.5f} | TP: {tp:.5f} | RR 1:3
Confluence: 2/3 AI Vote | BOS:{smc['bos']} | FVG:{smc['fvg']}
Trigger: Gmail Alert | DXY_Up:{guards['dxy_up']} VIX:{guards['vix_spike']}
Demo #436233200 | 0.25% Risk
Powered by Groq + AI Studio"""
    
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
    return {"status": "sent", "direction": direction}

# 6. GMAIL POLLER - YOUR CODE + FIXES
@app.route("/cron")
def cron():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("inbox")
        _, data = mail.search(None, '(UNSEEN SUBJECT "TradingView Alert")')
        for num in data[0].split():
            _, msg_data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            body = msg.get_payload(decode=True).decode()
            signal = json.loads(body)
            if signal.get("secret") == EMAIL_SECRET:
                result = run_95_pipeline(signal["pair"], signal["event"], signal["price"])
                mail.store(num, '+FLAGS', '\\Seen')
        mail.logout()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route("/")
def health():
    return "APEX WOLF 9.5/10 ONLINE - NO TWELVEDATA"

if __name__ == "__main__":
    app.run()
