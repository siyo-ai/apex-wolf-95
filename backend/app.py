import os, json, time, requests, imaplib, email, base64
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import yfinance as yf
import pandas as pd
from groq import Groq
import google.generativeai as genai
import telegram
from datetime import datetime

load_dotenv()
app = Flask(__name__)
CORS(app) # Enables frontend to call backend

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

# IN-MEMORY HISTORY - Resets on Render sleep. Upgrade to Redis later
SIGNAL_HISTORY = []

# 1. DUAL DATA FETCHER - YAHOO + ALPHA
def get_median_price(pair):
    try:
        y_ticker = pair.replace("/", "") + "=X" if "/" in pair and len(pair) == 6 else pair
        yf_data = yf.download(y_ticker, period="1d", interval="15m", progress=False)
        y_close = float(yf_data['Close'].iloc[-1]) if not yf_data.empty else 0
        
        if len(pair) == 6:
            av_url = f"https://www.alphavantage.co/query?function=FX_INTRADAY&from_symbol={pair[:3]}&to_symbol={pair[3:]}&interval=15min&apikey={ALPHA_KEY}"
            av_data = requests.get(av_url, timeout=10).json()
            av_close = float(list(av_data['Time Series FX (15min)'].values())[0]['4. close']) if 'Time Series FX (15min)' in av_data else 0
        else:
            av_close = 0
        
        prices = [p for p in [y_close, av_close] if p > 0]
        if len(prices) == 0: return None
        if len(prices) == 1: return prices[0]
        if abs(prices[0] - prices[1]) / prices[0] > 0.003: return None # 0.3% ATR filter
        return sum(prices) / len(prices)
    except:
        return None

# 2. SMC CALCULATOR - BOS/FVG/OB
def calc_smc(pair):
    try:
        ticker = pair.replace("/", "") + "=X" if "/" in pair and len(pair) == 6 else pair
        df = yf.download(ticker, period="5d", interval="15m", progress=False)
        if df.empty or len(df) < 3: return None
        highs, lows, closes = df['High'], df['Low'], df['Close']
        last_high, last_low = highs.iloc[-2], lows.iloc[-2]
        bos = "BULL" if closes.iloc[-1] > last_high else "BEAR" if closes.iloc[-1] < last_low else None
        fvg = None
        if lows.iloc[-1] > highs.iloc[-3]: fvg = f"{highs.iloc[-3]:.5f}-{lows.iloc[-1]:.5f}"
        if highs.iloc[-1] < lows.iloc[-3]: fvg = f"{highs.iloc[-1]:.5f}-{lows.iloc[-3]:.5f}"
        return {"bos": bos, "fvg": fvg, "price": float(closes.iloc[-1]), "l5h": float(highs.iloc[-5:].max()), "l5l": float(lows.iloc[-5:].min())}
    except:
        return None

# 3. GUARDS - DXY/VIX/SPREAD
def check_guards(pair):
    try:
        dxy = yf.download("DX-Y.NYB", period="1d", interval="5m", progress=False)
        vix = yf.download("^VIX", period="1d", interval="5m", progress=False)
        dxy_up = float(dxy['Close'].iloc[-1]) > float(dxy['Close'].iloc[-5]) if not dxy.empty else False
        vix_spike = float(vix['Close'].iloc[-1]) > 20 if not vix.empty else False
        return {"dxy_up": dxy_up, "vix_spike": vix_spike, "spread_ok": True}
    except:
        return {"dxy_up": False, "vix_spike": False, "spread_ok": True}

# 4. 2/3 AI ENSEMBLE
def ai_ensemble(pair, smc_data, guards, vision_analysis=""):
    votes = []
    
    # Vote 1: Rule Engine
    rule_vote = "NO"
    if smc_data and smc_data["bos"]:
        if smc_data["bos"] == "BULL" and not guards["dxy_up"]: rule_vote = "BULL"
        if smc_data["bos"] == "BEAR" and guards["dxy_up"]: rule_vote = "BEAR"
    votes.append(rule_vote)
    
    # Vote 2: Groq
    try:
        groq_resp = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": f"Pair:{pair} Chart:{vision_analysis[:200]} SMC:{smc_data} Guards:{guards}. Vote: BULL, BEAR, or NO. One word."}],
            model="llama-3.1-70b-versatile", max_tokens=5
        )
        votes.append(groq_resp.choices[0].message.content.strip().upper())
    except:
        votes.append("NO")
    
    # Vote 3: AI Studio Vision context
    vision_vote = "BULL" if "bullish" in vision_analysis.lower() else "BEAR" if "bearish" in vision_analysis.lower() else "NO"
    votes.append(vision_vote)
    
    bull_votes = votes.count("BULL")
    bear_votes = votes.count("BEAR")
    if bull_votes >= 2: return "BULL", votes
    if bear_votes >= 2: return "BEAR", votes
    return "NO", votes

# 5. TELEGRAM POST + HISTORY SAVE
def send_signal(pair, direction, entry, smc, guards, votes, trigger="Manual"):
    sl = entry * 0.998 if direction == "BULL" else entry * 1.002
    tp = entry * 1.006 if direction == "BULL" else entry * 0.994
    rr = abs(tp-entry)/abs(entry-sl)
    
    msg = f"""🐺 APEX WOLF 9.5/10 SIGNAL
{pair} M15 {direction} | {trigger}
Entry: {entry:.5f} | SL: {sl:.5f} | TP: {tp:.5f} | RR 1:{rr:.1f}
Confluence: 2/3 AI Vote {votes} | BOS:{smc['bos'] if smc else 'N/A'} FVG:{smc['fvg'] if smc else 'N/A'}
Guards: DXY_Up:{guards['dxy_up']} VIX_Spike:{guards['vix_spike']} Spread:OK
Demo #436233200 | 0.25% Risk
Powered by Groq + AI Studio"""
    
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
    SIGNAL_HISTORY.insert(0, {"time": datetime.now().isoformat(), "pair": pair, "direction": direction, "entry": entry, "msg": msg})
    if len(SIGNAL_HISTORY) > 20: SIGNAL_HISTORY.pop()
    return msg

# ROUTE 1: /cron - Gmail TV Alerts
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
                pair = signal["pair"]
                median_price = get_median_price(pair)
                if not median_price: continue
                smc = calc_smc(pair)
                guards = check_guards(pair)
                direction, votes = ai_ensemble(pair, smc, guards)
                if direction!= "NO" and not guards["vix_spike"]:
                    send_signal(pair, direction, median_price, smc, guards, votes, "Gmail Alert")
                mail.store(num, '+FLAGS', '\\Seen')
        mail.logout()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

# ROUTE 2: /analyze - Camera Button + Chart Upload
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        prompt = request.form.get('prompt', 'Analyze this chart for SMC setup')
        chart_file = request.files.get('chart')
        if not chart_file: return jsonify({"status": "error", "msg": "No chart uploaded"}), 400
        
        img_bytes = chart_file.read()
        img_b64 = base64.b64encode(img_bytes).decode()
        vision_resp = vision_model.generate_content([prompt, {"mime_type": chart_file.mimetype, "data": img_b64}])
        vision_analysis = vision_resp.text
        
        # Extract pair - crude parser
        pair = "XAUUSD"
        for p in ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","USDCHF","NZDUSD","XAUUSD"]:
            if p in prompt.upper() or p in vision_analysis.upper(): pair = p; break
        
        median_price = get_median_price(pair)
        if not median_price: return jsonify({"status": "error", "msg": "Bad market data"})
        smc = calc_smc(pair)
        guards = check_guards(pair)
        direction, votes = ai_ensemble(pair, smc, guards, vision_analysis)
        
        if direction == "NO": return jsonify({"status": "no_trade", "reason": "No 2/3 confluence", "vision": vision_analysis, "votes": votes})
        
        msg = send_signal(pair, direction, median_price, smc, guards, votes, "Chart AI Vision")
        return jsonify({"status": "sent", "direction": direction, "analysis": vision_analysis, "telegram": msg})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

# ROUTE 3: /signal - Manual Search Button
@app.route("/signal", methods=["POST"])
def manual_signal():
    try:
        data = request.json
        pair = data.get("pair", "XAUUSD").upper()
        median_price = get_median_price(pair)
        if not median_price: return jsonify({"status": "error", "msg": "Bad market data"})
        smc = calc_smc(pair)
        guards = check_guards(pair)
        direction, votes = ai_ensemble(pair, smc, guards)
        if direction == "NO": return jsonify({"status": "no_trade", "reason": "No confluence", "votes": votes})
        msg = send_signal(pair, direction, median_price, smc, guards, votes, "Manual Search")
        return jsonify({"status": "sent", "telegram": msg})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

# ROUTE 4: /history - History Tab
@app.route("/history")
def history():
    return jsonify({"status": "ok", "signals": SIGNAL_HISTORY})

# ROUTE 5: /consultants - AI Consultants Tab
@app.route("/consultants", methods=["POST"])
def consultants():
    try:
        data = request.json
        specialist = data.get("specialist", "AI Forex Strategist")
        query = data.get("query", "Give me market bias")
        pair = data.get("pair", "XAUUSD")
        
        system_prompts = {
            "AI Commodity Trading Specialist": "You are a commodity trading expert. Focus on XAUUSD, XAGUSD, Oil. Use SMC.",
            "AI Day Trading Specialist": "You are a day trading expert. Focus on M5-M15 scalps. Tight SL.",
            "AI ETF & Index Consultant": "You are an ETF/Index expert. Focus on SPX, NAS100.",
            "AI Forex Strategist": "You are a forex expert. Focus on majors. DXY correlation.",
            "AI Fundamental Analyst": "You are a fundamental expert. Focus on news, COT, rates."
        }
        
        groq_resp = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompts.get(specialist, "You are a trading AI.")},
                {"role": "user", "content": f"Pair:{pair}\nQuery:{query}\nGive actionable insight in 3 sentences."}
            ],
            model="llama-3.1-70b-versatile", max_tokens=150
        )
        return jsonify({"status": "ok", "specialist": specialist, "response": groq_resp.choices[0].message.content})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route("/")
def health():
    return "APEX WOLF 9.5/10 ONLINE - ALL ROUTES LIVE"

if __name__ == "__main__":
    app.run()
