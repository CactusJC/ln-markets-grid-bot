import os
import json
import yaml
import time
import logging
import sys
from dotenv import load_dotenv
from lnmarkets import rest

# Globale constante voor pauze tussen API-aanroepen (in seconden)
REQUEST_DELAY = 3.0

# Configureer of take-profit direct bij de order wordt ingesteld
USE_DIRECT_TAKE_PROFIT = True  # True voor directe methode

# Laad omgevingssleutels uit .env als fallback
load_dotenv()

# Configureer logging naar console en bestand
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("lnmarkets_test.log")
    ]
)

# Laad configuratie uit YAML-bestand
try:
    with open('configuration.yml', 'r') as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)
except Exception as e:
    logging.error("Fout bij laden van configuration.yml: %s", e)
    sys.exit(1)

# Haal API-sleutels uit config of .env
LN_KEY = config.get('key') or os.getenv('LN_KEY')
LN_SECRET = config.get('secret') or os.getenv('LN_SECRET')
LN_PASSPHRASE = config.get('passphrase') or os.getenv('LN_PASSPHRASE')

# Controleer of API-sleutels aanwezig zijn
if not all([LN_KEY, LN_SECRET, LN_PASSPHRASE]):
    logging.error("API-sleutels ontbreken! Controleer configuration.yml of .env.")
    sys.exit(1)

# Stel API-opties in
options = {
    'key': LN_KEY,
    'secret': LN_SECRET,
    'passphrase': LN_PASSPHRASE,
    'network': 'mainnet'
}

# Initialiseer LN Markets client
try:
    lnm = rest.LNMarketsRest(**options)
    test_response = lnm.futures_get_ticker()
    logging.info("Verbinding met LN Markets gelukt. Ticker: %s", test_response)
except Exception as e:
    logging.error("Fout bij initialiseren LN Markets client: %s", e)
    sys.exit(1)

# Helperfuncties
def parse_response(response):
    """Converteer API-response naar dictionary of lijst."""
    if isinstance(response, (dict, list)):
        return response
    try:
        return json.loads(response)
    except Exception as e:
        logging.error("Fout bij parsen response: %s", e)
        return {}

def usd_to_sats(usd_amount, btc_price):
    """Converteer USD naar satoshis (gehele getallen)."""
    try:
        return int(round((usd_amount / btc_price) * 1e8))
    except Exception as e:
        logging.error("Fout in usd_to_sats: %s", e)
        return 0

def get_ticker(lnm):
    """Haal de laatste marktprijs van LN Markets."""
    try:
        response = lnm.futures_get_ticker()
        ticker = parse_response(response)
        price = float(ticker.get('lastPrice', 0))
        if price <= 0:
            raise ValueError("Ongeldige prijs ontvangen")
        return price
    except Exception as e:
        logging.error("Fout bij ophalen ticker: %s", e)
        return None

def place_market_buy_order(lnm, margin_sats, leverage, takeprofit=None):
    """Plaats een markt kooporder met optionele take-profit."""
    try:
        params = {
            "type": "m",  # Marktorder
            "side": "b",  # Koop
            "margin": margin_sats,
            "leverage": leverage
        }
        if takeprofit is not None:
            params["takeprofit"] = takeprofit
        logging.debug("Orderparameters: %s", params)
        response = lnm.futures_new_trade(params)
        order = parse_response(response)
        if order.get('id'):
            logging.info("Order succesvol geplaatst: %s", order)
            return order
        else:
            logging.error("Order mislukt: %s", order)
            return None
    except Exception as e:
        logging.error("Fout bij plaatsen order: %s", e)
        return None

def place_limit_buy_order(lnm, margin_sats, leverage, price, takeprofit=None):
    """Plaats een limiet kooporder met optionele take-profit."""
    try:
        params = {
            "type": "l",  # Limietorder
            "side": "b",  # Koop
            "margin": margin_sats,
            "leverage": leverage,
            "price": price
        }
        if takeprofit is not None:
            params["takeprofit"] = takeprofit
        logging.debug("Orderparameters: %s", params)
        response = lnm.futures_new_trade(params)
        order = parse_response(response)
        if order.get('id'):
            logging.info("Limietorder succesvol geplaatst: %s", order)
            return order
        else:
            logging.error("Limietorder mislukt: %s", order)
            return None
    except Exception as e:
        logging.error("Fout bij plaatsen limietorder: %s", e)
        return None

def set_take_profit(lnm, trade_id, tp_price):
    """Stel take-profit in voor een bestaande trade via PUT-aanroep."""
    try:
        params = {
            "id": trade_id,
            "type": "takeprofit",
            "value": tp_price
        }
        logging.debug("PUT request parameters voor take-profit: %s", params)
        response = lnm.futures_update_trade(params)
        updated_order = parse_response(response)
        if updated_order.get('id'):
            logging.info("Take-profit succesvol ingesteld: %s", updated_order)
        else:
            logging.error("Take-profit instellen mislukt: %s", updated_order)
    except Exception as e:
        logging.error("Fout bij instellen take-profit: %s", e)

# Hoofdfunctie
def main():
    # Haal marktprijs op
    market_price = get_ticker(lnm)
    if not market_price:
        logging.error("Kan marktprijs niet ophalen. Script wordt beëindigd.")
        return

    # Bereken margin in satoshis voor $5
    usd_amount = 5
    margin_sats = usd_to_sats(usd_amount, market_price)
    if margin_sats <= 0:
        logging.error("Ongeldige margin berekend. Script wordt beëindigd.")
        return
    logging.info("Margin berekend: %d satoshis voor $%d bij prijs %.2f", margin_sats, usd_amount, market_price)

    # Plaats eerste markt kooporder (geen take-profit)
    logging.info("Plaats eerste markt kooporder voor $5 met hefboom 1")
    first_order = place_market_buy_order(lnm, margin_sats, 1)
    if not first_order:
        logging.error("Eerste order mislukt. Script wordt beëindigd.")
        return

    # Wacht om rate limits te respecteren
    time.sleep(REQUEST_DELAY)

    # Plaats tweede markt kooporder met take-profit
    logging.info("Plaats tweede markt kooporder voor $5 met hefboom 1")
    if USE_DIRECT_TAKE_PROFIT:
        # Methode 1: Take-profit direct bij order
        tp_price = round(market_price * 1.01)
        logging.info("Take-profit direct ingesteld op %.0f (1%% boven geschatte marktprijs %.2f)", tp_price, market_price)
        second_order = place_market_buy_order(lnm, margin_sats, 1, takeprofit=tp_price)
        if second_order:
            entry_price = second_order.get('entry_price', market_price)
            actual_tp_target = round(entry_price * 1.01)
            logging.info("Werkelijke entry_price: %.2f, geschatte take-profit: %.0f, ideale take-profit: %.0f", 
                         entry_price, tp_price, actual_tp_target)
    else:
        # Methode 2: Take-profit achteraf via PUT
        second_order = place_market_buy_order(lnm, margin_sats, 1)
        if second_order:
            entry_price = second_order.get('entry_price')
            if entry_price:
                tp_price = round(entry_price * 1.01)
                logging.info("Take-profit ingesteld op %.0f (1%% boven entry_price %.2f)", tp_price, entry_price)
                set_take_profit(lnm, second_order['id'], tp_price)
            else:
                logging.error("Entry_price niet gevonden voor tweede order.")

    if not second_order:
        logging.error("Tweede order mislukt. Script wordt beëindigd.")
        return

    # Wacht om rate limits te respecteren
    time.sleep(REQUEST_DELAY)

    # Test een limiet kooporder met take-profit van 1%
    logging.info("Plaats test limiet kooporder voor $5 met hefboom 1")
    limit_price = round(market_price - 100)  # 100 USD onder marktprijs, afgerond naar heel getal
    limit_take_profit = round(limit_price * 1.01)  # 1% boven limietprijs, afgerond naar heel getal
    limit_order = place_limit_buy_order(lnm, margin_sats, 1, limit_price, takeprofit=limit_take_profit)
    if not limit_order:
        logging.error("Limietorder mislukt.")
    else:
        logging.info("Limietorder succesvol geplaatst op prijs %.0f met take-profit %.0f", limit_price, limit_take_profit)

if __name__ == "__main__":
    main()
