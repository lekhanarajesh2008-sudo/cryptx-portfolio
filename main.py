
import logging
import os
import time

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# --------------------------------------------------
# 1. APPLICATION CONFIGURATION
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger("cryptx")

app = FastAPI(
    title="Crypto Intelligence API",
    description="Backend API for CRYPTX Portfolio",
    version="2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

BASE_URL = "https://api.coingecko.com/api/v3"

COINS = ["bitcoin", "ethereum", "solana"]

# --------------------------------------------------
# 2. HTTP SESSION AND CACHE
# --------------------------------------------------

session = requests.Session()

session.headers.update({
    "Accept": "application/json",
    "User-Agent": "CRYPTX-Portfolio/2.0"
})

# Cache format: key -> (timestamp, response data)
cache = {}


# --------------------------------------------------
# 3. CENTRAL API REQUEST FUNCTION
# --------------------------------------------------

def get_data(key, url, params=None, cache_seconds=120):

    current_time = time.time()

    # Check fresh cache first
    if key in cache:
        saved_time, saved_data = cache[key]

        if current_time - saved_time < cache_seconds:
            logger.info("CACHE HIT: %s", key)
            return saved_data

    logger.info("REQUEST STARTED: %s", key)

    last_error = None
    upstream_status = None

    # Try the external API twice
    for attempt in range(1, 3):

        try:
            logger.info(
                "CoinGecko request: %s, attempt %s",
                key,
                attempt
            )

            response = session.get(
                url,
                params=params,
                timeout=(5, 15)
            )

            upstream_status = response.status_code

            logger.info(
                "CoinGecko response for %s: HTTP %s",
                key,
                upstream_status
            )

            response.raise_for_status()

            data = response.json()

            # Save successful response
            cache[key] = (time.time(), data)

            logger.info("REQUEST SUCCESSFUL: %s", key)

            return data

        except requests.exceptions.HTTPError as error:

            last_error = error

            logger.exception(
                "COINGECKO HTTP ERROR for %s",
                key
            )

            # Retry rate limits and server errors once
            if upstream_status not in (429, 500, 502, 503, 504):
                break

        except requests.exceptions.RequestException as error:

            last_error = error

            logger.exception(
                "COINGECKO CONNECTION ERROR for %s",
                key
            )

        except ValueError as error:

            last_error = error

            logger.exception(
                "COINGECKO INVALID JSON for %s",
                key
            )

            break

        if attempt < 2:
            time.sleep(1)

    # Use stale cached data if available
    if key in cache:

        logger.warning(
            "USING STALE CACHE: %s",
            key
        )

        return cache[key][1]

    # Nothing available: return controlled error
    logger.error(
        "API FAILED: key=%s status=%s error=%r",
        key,
        upstream_status,
        last_error
    )

    raise HTTPException(
        status_code=503,
        detail={
            "message": "Crypto market data is temporarily unavailable.",
            "source": "CoinGecko",
            "endpoint": key,
            "upstream_status": upstream_status,
            "error_type": (
                type(last_error).__name__
                if last_error else "UnknownError"
            )
        }
    )


# --------------------------------------------------
# 4. HOME AND HEALTH ENDPOINTS
# --------------------------------------------------

@app.get("/")
def home():

    return {
        "message": "CRYPTX Crypto Intelligence API is running",
        "status": "online"
    }


@app.get("/health")
def health():

    return {
        "status": "healthy",
        "service": "CRYPTX Backend"
    }


# --------------------------------------------------
# 5. MARKET DATA
# --------------------------------------------------

@app.get("/markets")
def markets():

    data = get_data(
        "markets",
        BASE_URL + "/simple/price",
        {
            "ids": ",".join(COINS),
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        },
        120
    )

    return data


# --------------------------------------------------
# 6. CRYPTO DETAILS
# --------------------------------------------------

@app.get("/crypto")
def crypto_data():

    data = markets()

    return {
        "name": "Bitcoin",
        "symbol": "BTC",
        "price": data["bitcoin"]["usd"],
        "market_status": "Active"
    }


# --------------------------------------------------
# 7. MARKET ANALYSIS
# --------------------------------------------------

@app.get("/analysis")
def analysis():

    data = markets()

    change = data["bitcoin"].get(
        "usd_24h_change", 0
    )

    if change > 2:

        trend = "Bullish"
        prediction = "Positive momentum"
        risk = "Moderate"

    elif change < -2:

        trend = "Bearish"
        prediction = "Negative momentum"
        risk = "High"

    else:

        trend = "Sideways"
        prediction = "Market is relatively stable"
        risk = "Moderate"

    return {
        "trend": trend,
        "prediction": prediction,
        "risk_level": risk,
        "bitcoin_24h_change": change
    }


# --------------------------------------------------
# 8. BITCOIN PRICE HISTORY
# --------------------------------------------------

@app.get("/history")
@app.get("/portfolio/history")
@app.get("/portfolio-history")
def history():

    data = get_data(
        "bitcoin_history",
        BASE_URL + "/coins/bitcoin/market_chart",
        {
            "vs_currency": "usd",
            "days": "1"
        },
        300
    )

    return {
        "prices": data["prices"]
    }


# --------------------------------------------------
# 9. COMPARISON HISTORY
# --------------------------------------------------

@app.get("/comparison-history")
def comparison_history():

    result = {}

    for coin in COINS:

        data = get_data(
            coin + "_comparison",
            BASE_URL + "/coins/" + coin + "/market_chart",
            {
                "vs_currency": "usd",
                "days": "1"
            },
            600
        )

        result[coin] = data["prices"]

    return {
        "history": result
    }


# --------------------------------------------------
# 10. RUNNING INFORMATION
# --------------------------------------------------

@app.get("/api/status")
def api_status():

    return {
        "application": "CRYPTX",
        "backend": "running",
        "market_provider": "CoinGecko",
        "cached_items": list(cache.keys())
    }
