import requests
import os
import time
from datetime import datetime

# ─── Config (GitHub Secrets se aayega) ───────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT   = os.environ.get("TELEGRAM_CHAT_ID", "")
WARNING_LEVEL   = 400
SIGNAL_LEVEL    = 500

def send_telegram(message, urgent=False):
    """Telegram pe message bhejo"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print("Telegram config missing")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print(f"✅ Telegram message sent")
        else:
            print(f"Telegram error: {r.text}")
    except Exception as e:
        print(f"Telegram failed: {e}")

def parse_n(val):
    if val is None or str(val).strip() in ['-', '']:
        return 0
    try:
        return float(str(val).replace(',', ''))
    except:
        return 0

def fetch_nse():
    """NSE se data fetch karo"""
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
    }
    
    session = requests.Session()
    
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=15)
        time.sleep(3)
        session.get("https://www.nseindia.com/option-chain", headers=headers, timeout=15)
        time.sleep(2)
        
        r = session.get(url, headers=headers, timeout=20)
        
        if r.status_code == 200:
            return r.json()
        else:
            print(f"NSE error: {r.status_code}")
            return None
    except Exception as e:
        print(f"Fetch error: {e}")
        return None

def analyze(data):
    """Signal dhundho"""
    if not data or 'records' not in data:
        return [], 0, 0
    
    records  = data['records']
    spot     = parse_n(records.get('underlyingValue', 0))
    atm      = round(spot / 50) * 50
    options  = records.get('data', [])
    results  = []
    
    for item in options:
        strike = item.get('strikePrice', 0)
        if abs(strike - atm) > 300:
            continue
        
        ce = item.get('CE', {})
        pe = item.get('PE', {})
        
        ce_oi  = parse_n(ce.get('openInterest', 0))
        ce_chg = parse_n(ce.get('changeinOpenInterest', 0))
        ce_ltp = parse_n(ce.get('lastPrice', 0))
        pe_oi  = parse_n(pe.get('openInterest', 0))
        pe_chg = parse_n(pe.get('changeinOpenInterest', 0))
        pe_ltp = parse_n(pe.get('lastPrice', 0))
        
        ce_prev = ce_oi - ce_chg
        pe_prev = pe_oi - pe_chg
        ce_pct  = (ce_chg / ce_prev * 100) if ce_prev > 0 and ce_chg > 0 else 0
        pe_pct  = (pe_chg / pe_prev * 100) if pe_prev > 0 and pe_chg > 0 else 0
        
        results.append({
            'strike': strike,
            'ce_pct': ce_pct, 'ce_ltp': ce_ltp,
            'pe_pct': pe_pct, 'pe_ltp': pe_ltp,
        })
    
    return results, spot, atm

def main():
    now = datetime.utcnow()
    ist_hour   = (now.hour + 5) % 24
    ist_minute = (now.minute + 30) % 60
    ist_time   = f"{ist_hour:02d}:{ist_minute:02d}"
    
    print(f"🕐 IST Time: {ist_time}")
    print(f"📡 NSE data fetch kar raha hun...")
    
    data = fetch_nse()
    
    if not data:
        msg = f"⚠️ OI Monitor\n\nNSE data fetch nahi hua ({ist_time} IST)\nManually check karo: nseindia.com/option-chain"
        send_telegram(msg)
        return
    
    results, spot, atm = analyze(data)
    
    if not results:
        print("No data parsed")
        return
    
    print(f"✅ Nifty Spot: {spot:.0f} | ATM: {atm}")
    
    signals_found  = []
    warnings_found = []
    
    for r in results:
        strike = r['strike']
        
        # CE Short Buildup → Buy PUT
        if r['ce_pct'] >= SIGNAL_LEVEL:
            entry = r['pe_ltp']
            sl    = round(entry * 0.80, 1)
            t1    = round(entry * 1.50, 1)
            signals_found.append({
                'type': 'PUT (PE)', 'strike': strike,
                'pct': r['ce_pct'], 'side': 'CE',
                'entry': entry, 'sl': sl, 't1': t1
            })
        elif r['ce_pct'] >= WARNING_LEVEL:
            warnings_found.append({
                'strike': strike, 'side': 'CE',
                'pct': r['ce_pct'], 'watch': 'PUT'
            })
        
        # PE Short Buildup → Buy CALL
        if r['pe_pct'] >= SIGNAL_LEVEL:
            entry = r['ce_ltp']
            sl    = round(entry * 0.80, 1)
            t1    = round(entry * 1.50, 1)
            signals_found.append({
                'type': 'CALL (CE)', 'strike': strike,
                'pct': r['pe_pct'], 'side': 'PE',
                'entry': entry, 'sl': sl, 't1': t1
            })
        elif r['pe_pct'] >= WARNING_LEVEL:
            warnings_found.append({
                'strike': strike, 'side': 'PE',
                'pct': r['pe_pct'], 'watch': 'CALL'
            })
    
    # SIGNAL messages
    for s in signals_found:
        msg = f"""🚨 <b>OI SIGNAL MILA!</b>

📍 <b>BUY {s['type']}</b>
⚡ Strike: <b>{s['strike']}</b>
📊 {s['side']} OI Change: <b>{s['pct']:.0f}%</b>
🕐 Time: {ist_time} IST
📈 Nifty Spot: {spot:.0f}

💰 <b>Entry ~₹{s['entry']}</b>
🛑 Stop Loss: ₹{s['sl']}
🎯 Target 1: ₹{s['t1']}

⚠️ <i>Paper trade hai — real paisa mat lagao abhi</i>"""
        
        send_telegram(msg)
        print(f"🚨 SIGNAL: BUY {s['type']} {s['strike']} | {s['pct']:.0f}%")
    
    # WARNING messages
    for w in warnings_found:
        msg = f"""⚠️ <b>OI WARNING — Alert Raho!</b>

📍 Strike: <b>{w['strike']}</b>
📊 {w['side']} OI Change: <b>{w['pct']:.0f}%</b>
👀 Watch: <b>{w['watch']}</b> side
🕐 Time: {ist_time} IST

Signal aane wala ho sakta hai.
NSE check karo: nseindia.com/option-chain"""
        
        send_telegram(msg)
        print(f"⚠️ WARNING: {w['strike']} {w['side']} {w['pct']:.0f}%")
    
    # Koi signal nahi
    if not signals_found and not warnings_found:
        print(f"✅ No signal ({ist_time}) — market normal")
        # Sirf ek baar subah status bhejo
        if ist_hour == 9 and 15 <= ist_minute <= 20:
            msg = f"""📊 <b>OI Monitor Active</b>

✅ System chal raha hai
🕐 {ist_time} IST
📈 Nifty: {spot:.0f} | ATM: {atm}

Abhi koi signal nahi. Alert rahega! 👀"""
            send_telegram(msg)

if __name__ == "__main__":
    main()
