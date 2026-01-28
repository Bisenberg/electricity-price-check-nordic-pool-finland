import requests
import datetime
import pytz
import os
import sys
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
QUARTER_HOUR_MINUTES = 15
QUARTERS_PER_HOUR = 4
DEFAULT_TIMEZONE = "Europe/Helsinki"
DEFAULT_START_HOUR = 7
DEFAULT_END_HOUR = 21
REQUEST_TIMEOUT = 10

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        conf = json.load(f)
except FileNotFoundError:
    logger.error(f"Config file not found at {CONFIG_PATH}")
    sys.exit(1)
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON in config.json: {e}")
    sys.exit(1)

TELEGRAM_BOT_TOKEN = conf.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = conf.get("TELEGRAM_CHAT_ID")
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("Missing required config: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    sys.exit(1)

TIMEZONE = conf.get("TIMEZONE", DEFAULT_TIMEZONE)
START_HOUR = int(conf.get("START_HOUR", DEFAULT_START_HOUR))
END_HOUR = int(conf.get("END_HOUR", DEFAULT_END_HOUR))

if not 0 <= START_HOUR < 24 or not 0 <= END_HOUR <= 24 or START_HOUR >= END_HOUR:
    logger.error(f"Invalid hours: START_HOUR={START_HOUR}, END_HOUR={END_HOUR}")
    sys.exit(1)

def get_prices_from_sahkotin(start, end):
    """Fetch electricity prices from Sahkotin API.
    
    Args:
        start: UTC datetime for start of period
        end: UTC datetime for end of period
    
    Returns:
        List of price dictionaries from the API
    """
    params = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "fix": "",
        "vat": "",
    }
    # Returns prices every quarter hour in snt/kWh with VAT included
    url = "https://sahkotin.fi/prices"
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["prices"]
    except requests.exceptions.Timeout:
        logger.error("Request to Sahkotin API timed out")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching prices from Sahkotin: {e}")
        raise

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
    """Send a message via Telegram bot.
    
    Args:
        text: Message text to send
    
    Raises:
        requests.exceptions.RequestException: If the request fails
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        logger.info("Telegram message sent successfully")
    except requests.exceptions.Timeout:
        logger.error("Telegram API request timed out")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        raise

def format_price_line(index, dt, val):
    next_quarter = dt + datetime.timedelta(minutes=QUARTER_HOUR_MINUTES)
    return f"{index}. {dt.strftime('%H:%M')}–{next_quarter.strftime('%H:%M')}: {val:.2f} snt/kWh"



def find_cheapest_hour(prices):
    """Find the cheapest 1-hour block (4 quarters) in the price list.
    
    Args:
        prices: List of (datetime, price) tuples
    
    Returns:
        Tuple of (block, average_price) or (None, None) if not enough data
    """
    if len(prices) < QUARTERS_PER_HOUR:
        return None, None

    cheapest_block = None
    cheapest_avg = float("inf")

    for i in range(len(prices) - QUARTERS_PER_HOUR + 1):
        block = prices[i:i+QUARTERS_PER_HOUR]
        avg_price = sum(p[1] for p in block) / QUARTERS_PER_HOUR
        if avg_price < cheapest_avg:
            cheapest_avg = avg_price
            cheapest_block = block

    return cheapest_block, cheapest_avg

def format_cheapest_hour(prices):
    """Format the cheapest hour block as a readable string.
    
    Args:
        prices: List of (datetime, price) tuples
    
    Returns:
        Formatted string or None if no block found
    """
    block, avg = find_cheapest_hour(prices)
    if not block:
        return None

    start = block[0][0]
    end = block[-1][0] + datetime.timedelta(minutes=QUARTER_HOUR_MINUTES)
    return "Cheapest 1-hour block: {}–{} ({:.2f} snt/kWh average)".format(
        start.strftime("%H:%M"), end.strftime("%H:%M"), avg
    )

def main():
    """Main function to fetch and report electricity prices."""
    try:
        logger.info("Starting electricity price check")
        tz = pytz.timezone(TIMEZONE)
        today = datetime.datetime.now(tz).date()
        start_local = datetime.datetime.combine(today, datetime.time(0, 0))
        end_local = start_local + datetime.timedelta(days=1)
        start_utc = tz.localize(start_local).astimezone(pytz.utc)
        end_utc = tz.localize(end_local).astimezone(pytz.utc)

        logger.info("Fetching electricity prices")
        prices = get_prices_from_sahkotin(start_utc, end_utc)
        filtered = filter_prices(prices, START_HOUR, END_HOUR)

        if not filtered:
            logger.warning("No electricity price data found for today")
            send_telegram_message("No electricity price data found for today.")
            return

        # Get top 3 cheapest quarters
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
        logger.info("Sending message via Telegram")
        print(message)
        send_telegram_message(message)
        logger.info("Electricity price check completed successfully")
    except Exception as e:
        logger.error(f"Error running bot: {e}", exc_info=True)
        try:
            send_telegram_message(f"Error running bot: {e}")
        except Exception as send_error:
            logger.error(f"Failed to send error message to Telegram: {send_error}")


if __name__ == "__main__":
    main()
