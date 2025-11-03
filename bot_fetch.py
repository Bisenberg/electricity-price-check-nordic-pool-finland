import requests
import datetime
import pytz
import os
import sys
import json

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        conf = json.load(f)
except Exception as e:
    print(f"Error loading config.json: {e}")
    sys.exit(1)
    
TELEGRAM_BOT_TOKEN = conf["TELEGRAM_BOT_TOKEN"]
CHAT_ID = conf["CHAT_ID"]
TIMEZONE = conf.get("TIMEZONE", "Europe/Helsinki")
START_HOUR = int(conf.get("START_HOUR", 8))
END_HOUR = int(conf.get("END_HOUR", 21))

def get_prices_from_sahkotin(start, end):
    params = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "fix": "",
        "vat": "",
    }
    url = "https://sahkotin.fi/prices?quarter&fix&vat"
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()["prices"]

def local_to_utc(dt_local):
    tz = pytz.timezone(TIMEZONE)
    return tz.localize(dt_local).astimezone(pytz.utc)

def find_lowest_between(prices, start_hour, end_hour):
    tz = pytz.timezone(TIMEZONE)
    filtered = []
    for p in prices:
        dt = datetime.datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        dt_local = dt.astimezone(tz)
        if start_hour <= dt_local.hour < end_hour:
            filtered.append((dt_local, p["value"]))
    if not filtered:
        return None, None
    return min(filtered, key=lambda x: x[1])

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)


def main():
    tz = pytz.timezone(TIMEZONE)
    today = datetime.datetime.now(tz).date()
    start_local = datetime.datetime.combine(today, datetime.time(0, 0))
    end_local = start_local + datetime.timedelta(days=1)
    start_utc = local_to_utc(start_local)
    end_utc = local_to_utc(end_local)
    print("Looking for electricity prices.")
    prices = get_prices_from_sahkotin(start_utc, end_utc)

    dt_low, val_low = find_lowest_between(prices, START_HOUR, END_HOUR)
    print(f"Lowest value: {val_low:.2f}snt/kWh at {dt_low.strftime('%H:%M')} ")
    if dt_low:
        msg = f"Cheapest electricity today between 08–21: {val_low:.2f} snt/kWh at {dt_low.strftime('%H:%M')}"
    else:
        msg = "No electricity price data found for today."
        
    print("Sending message")    
    send_telegram_message(msg)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_telegram_message(f"Error running bot: {e}")
        
        
