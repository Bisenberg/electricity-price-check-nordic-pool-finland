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
TELEGRAM_CHAT_ID = conf["TELEGRAM_CHAT_ID"]
TIMEZONE = conf.get("TIMEZONE", "Europe/Helsinki")
START_HOUR = int(conf.get("START_HOUR", 7))
END_HOUR = int(conf.get("END_HOUR", 21))

def get_prices_from_sahkotin(start, end):
    params = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "fix": "",
        "vat": "",
    }
    url = "https://sahkotin.fi/prices?quarter&fix&vat" # Get prices every quarter hour, change price to snt/kWh, add VAT to price 
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()["prices"]

# Helsinki time
def local_to_utc(dt_local):
    tz = pytz.timezone(TIMEZONE)
    return tz.localize(dt_local).astimezone(pytz.utc)

def filter_prices(prices, start_hour, end_hour):
    tz = pytz.timezone(TIMEZONE)
    today = datetime.datetime.now(tz).date()
    filtered = []
    for p in prices:
        dt = datetime.datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        dt_local = dt.astimezone(tz)
        if dt_local.date() == today and start_hour <= dt_local.hour < end_hour:
            filtered.append((dt_local, p["value"]))
    return filtered

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)

def format_price_line(index, dt, val):
    next_quarter = dt + datetime.timedelta(minutes=15)
    return f"{index}. {dt.strftime('%H:%M')}–{next_quarter.strftime('%H:%M')}: {val:.2f} snt/kWh"



def find_cheapest_hour(prices):

    if len(prices) < 4:
        return None, None

    cheapest_block = None
    cheapest_avg = float("inf")

    for i in range(len(prices) - 3):
        block = prices[i:i+4]
        avg_price = sum(p[1] for p in block) / 4
        if avg_price < cheapest_avg:
            cheapest_avg = avg_price
            cheapest_block = block

    return cheapest_block, cheapest_avg

def format_cheapest_hour(prices):

    block, avg = find_cheapest_hour(prices)
    if not block:
        return None

    start = block[0][0]
    end = block[-1][0] + datetime.timedelta(minutes=15)
    return "Cheapest 1-hour block: {}–{} ({:.2f} snt/kWh average)".format(
        start.strftime("%H:%M"), end.strftime("%H:%M"), avg
    )

def main():
    tz = pytz.timezone(TIMEZONE)
    today = datetime.datetime.now(tz).date()
    start_local = datetime.datetime.combine(today, datetime.time(0, 0))
    end_local = start_local + datetime.timedelta(days=1)
    start_utc = local_to_utc(start_local)
    end_utc = local_to_utc(end_local)

    print("Fetching electricity prices")
    prices = get_prices_from_sahkotin(start_utc, end_utc)
    filtered = filter_prices(prices, START_HOUR, END_HOUR)

    if not filtered:
        send_telegram_message("No electricity price data found for today.")
        return

    sorted_prices = sorted(filtered, key=lambda x: x[1])
    top3 = sorted_prices[:3]

    lines = ["Three Cheapest Quarters Today ({}–{}):".format(START_HOUR, END_HOUR)]
    lines.extend(format_price_line(i, dt, val) for i, (dt, val) in enumerate(top3, start=1))

    avg_price = sum(price for _, price in filtered) / len(filtered)
    lines.append("")
    lines.append(f"Average price today: {avg_price:.2f} snt/kWh")
    
    cheapest_hour_text = format_cheapest_hour(filtered)
    if cheapest_hour_text:
        lines.append("")
        lines.append(cheapest_hour_text)

    message = "\n".join(lines)
    print(message)
    send_telegram_message(message)
    print("Message sent successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_telegram_message(f"Error running bot: {e}")
        
        
