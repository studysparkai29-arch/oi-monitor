import os
import time
import requests
from datetime import datetime

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT   = os.environ.get("TELEGRAM_CHAT_ID", "")
WARNING_LEVEL   = 400
SIGNAL_LEVEL    = 500

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print("Telegram config missing")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        if r.status_code == 200:
            print("Telegram message sent")
            return True
        else:
            print(f"Telegram error: {r.text}")
            return False
    except Exception as e:
        print(f"Telegram failed: {e}")
        return False

def parse_n(val):
    if val is None or str(val).strip() in ['-', '']:
        return 0
    try:
        return float(str(val).replace(',', ''))
    except:
        return 0

def fetch_nse_data():
    # Method 1: nsepython
    try:
        print("nsepython try kar raha hun...")
        from nsepython import nse_optionchain_scrapper
        data = nse_optionchain_scrapper("NIFTY")
        if data and 'records' in data:
            print("nsepython se data mila!")
            return data
    except Exception as e:
        print(f"nsepython failed: {e}")

    # Method 2: Direct NSE
    try:
        print("Direct NSE try kar raha hun...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/option-chain",
        }
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=15)
        time.sleep(3)
        session.get("https://www.nseindia.com/option-chain", headers=headers, timeout=15)
        time.sleep(2)
        r = session.get(
            "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",
            headers=headers, timeout=20
        )
        if r.status_code == 200:
            print("Direct NSE se data mila!")
            return r.json()
    except Exception as e:
        print(f"Direct NSE failed: {e}")

    return None

def analyze(data):
    if not data or 'records' not in data:
        return [], 0, 0
    records = data['records']
    spot    = parse_n(records.get('underlyingValue', 0))
    atm     = round(spot / 50) * 50
    options = records.get('data', [])
    results = []
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
    now_utc  = datetime.utcnow()
    ist_hour = (now_utc.hour + 5) % 24
    ist_min  = (now_utc.minute + 30) % 60
    ist_time = f"{ist_hour:02d}:{ist_min:02d}"
    print(f"IST Time: {ist_time}")

    data = fetch_nse_data()

    if not data:
        msg = f"⚠️ <b>OI Monitor</b>\n\nNSE data fetch nahi hua ({ist_time} IST)\nManually check karo: nseindia.com/option-chain"
        send_telegram(msg)
        return

    results, spot, atm = analyze(data)
    if not results:
        print("No results")
        return

    print(f"Nifty: {spot:.0f} | ATM: {atm}")

    signals  = []
    warnings = []

    for r in results:
        strike = r['strike']
        if r['ce_pct'] >= SIGNAL_LEVEL:
            entry = r['pe_ltp']
            signals.append({'action': 'BUY PUT (PE)', 'strike': strike, 'pct': r['ce_pct'], 'side': 'CE', 'entry': entry, 'sl': round(entry*0.8,1), 't1': round(entry*1.5,1), 't2': round(entry*1.8,1)})
        elif r['ce_pct'] >= WARNING_LEVEL:
            warnings.append({'strike': strike, 'side': 'CE', 'pct': r['ce_pct'], 'watch': 'PUT'})
        if r['pe_pct'] >= SIGNAL_LEVEL:
            entry = r['ce_ltp']
            signals.append({'action': 'BUY CALL (CE)', 'strike': strike, 'pct': r['pe_pct'], 'side': 'PE', 'entry': entry, 'sl': round(entry*0.8,1), 't1': round(entry*1.5,1), 't2': round(entry*1.8,1)})
        elif r['pe_pct'] >= WARNING_LEVEL:
            warnings.append({'strike': strike, 'side': 'PE', 'pct': r['pe_pct'], 'watch': 'CALL'})

    for s in signals:
        msg = f"""🚨 <b>OI SIGNAL MILA!</b>

📍 <b>{s['action']}</b>
⚡ Strike: <b>{s['strike']}</b>
📊 {s['side']} OI Change: <b>{s['pct']:.0f}%</b>
🕐 Time: {ist_time} IST
📈 Nifty Spot: {spot:.0f}

💰 <b>Entry ~₹{s['entry']}</b>
🛑 Stop Loss: ₹{s['sl']}
🎯 Target 1: ₹{s['t1']}
🎯 Target 2: ₹{s['t2']}

⚠️ <i>Paper trade — real paisa mat lagao abhi</i>"""
        send_telegram(msg)

    for w in warnings:
        msg = f"""⚠️ <b>OI WARNING — Alert Raho!</b>

📍 Strike: <b>{w['strike']}</b>
📊 {w['side']} OI Change: <b>{w['pct']:.0f}%</b>
👀 Watch: <b>{w['watch']}</b> side
🕐 Time: {ist_time} IST

Signal aa sakta hai — ready raho!"""
        send_telegram(msg)

    if not signals and not warnings:
        print(f"No signal at {ist_time}")
        if ist_hour == 9 and 14 <= ist_min <= 20:
            msg = f"📊 <b>OI Monitor Active</b>\n\n✅ System chal raha hai\n🕐 {ist_time} IST\n📈 Nifty: {spot:.0f} | ATM: {atm}\n\nKoi signal nahi abhi 👀"
            send_telegram(msg)

if __name__ == "__main__":
    main()
