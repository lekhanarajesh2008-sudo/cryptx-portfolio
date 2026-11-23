
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path

import requests
import time
import threading
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


# ==================================================
# CRYPTX CONFIGURATION
# ==================================================

app = FastAPI(
    title="CRYPTX Crypto Portfolio API",
    description="Backend API for CRYPTX",
    version="2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ==================================================
# COINGECKO PUBLIC API
# No API key required
# ==================================================

BASE_URL = "https://api.coingecko.com/api/v3"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "CRYPTX-Crypto-Portfolio/2.0"
}
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

if COINGECKO_API_KEY:
    HEADERS["x-cg-demo-api-key"] = COINGECKO_API_KEY

# Cache durations
MARKET_CACHE_SECONDS = 120
HISTORY_CACHE_SECONDS = 300
COMPARISON_CACHE_SECONDS = 600

# Maximum age of cached data used during an outage
MAX_STALE_CACHE_SECONDS = 86400

# Cooldown defaults
DEFAULT_429_COOLDOWN = 60
SERVER_ERROR_COOLDOWN = 20
CONNECTION_ERROR_COOLDOWN = 15

# Cache format:
# key: (timestamp, data)
cache = {}

# Global CoinGecko rate-limit cooldown
rate_limit_until = 0

# Per-endpoint cooldown after temporary failures
endpoint_cooldowns = {}

# Prevent simultaneous upstream requests
request_lock = threading.Lock()


# ==================================================
# RETRY-AFTER HANDLING
# ==================================================

def get_retry_after(response):

    retry_after = response.headers.get("Retry-After")

    if not retry_after:
        return DEFAULT_429_COOLDOWN

    # Retry-After may contain seconds
    try:
        return max(1, int(retry_after))
    except (ValueError, TypeError):
        pass

    # Or it may contain an HTTP date
    try:
        retry_date = parsedate_to_datetime(retry_after)

        if retry_date.tzinfo is None:
            retry_date = retry_date.replace(
                tzinfo=timezone.utc
            )

        seconds = (
            retry_date - datetime.now(timezone.utc)
        ).total_seconds()

        return max(1, int(seconds))

    except (ValueError, TypeError, OverflowError):
        return DEFAULT_429_COOLDOWN


# ==================================================
# CACHE HELPERS
# ==================================================

def get_cached_data(key, allow_stale=False):

    entry = cache.get(key)

    if entry is None:
        return None

    saved_time, saved_data = entry

    age = time.time() - saved_time

    if allow_stale:
        if age <= MAX_STALE_CACHE_SECONDS:
            return saved_data

        return None

    return saved_data if age < get_cache_duration(key) else None


def get_cache_duration(key):

    if key == "markets":
        return MARKET_CACHE_SECONDS

    if key == "bitcoin_history":
        return HISTORY_CACHE_SECONDS

    if key.endswith("_comparison"):
        return COMPARISON_CACHE_SECONDS

    return MARKET_CACHE_SECONDS


def save_cache(key, data):

    cache[key] = (time.time(), data)


# ==================================================
# ERROR RESPONSE
# ==================================================

def unavailable(message, retry_after=None):

    detail = {
        "message": message,
        "source": "CoinGecko"
    }

    headers = None

    if retry_after is not None:

        retry_after = max(1, int(retry_after))

        detail["retry_after_seconds"] = retry_after

        headers = {
            "Retry-After": str(retry_after)
        }

    raise HTTPException(
        status_code=503,
        detail=detail,
        headers=headers
    )


# ==================================================
# MAIN COINGECKO REQUEST FUNCTION
# ==================================================

def get_data(key, endpoint, params):

    global rate_limit_until

    now = time.time()

    # 1. Return fresh cache immediately
    cached = get_cached_data(key)

    if cached is not None:
        return cached

    # 2. Only one request to CoinGecko at a time
    with request_lock:

        # Check cache again after waiting
        cached = get_cached_data(key)

        if cached is not None:
            return cached

        now = time.time()

        # 3. Respect global 429 cooldown
        if now < rate_limit_until:

            stale = get_cached_data(
                key,
                allow_stale=True
            )

            if stale is not None:
                return stale

            remaining = int(rate_limit_until - now) + 1

            unavailable(
                "CoinGecko rate limit is active. "
                "Please wait before requesting fresh data.",
                remaining
            )

        # 4. Respect endpoint-specific cooldown
        endpoint_wait = endpoint_cooldowns.get(key, 0)

        if now < endpoint_wait:

            stale = get_cached_data(
                key,
                allow_stale=True
            )

            if stale is not None:
                return stale

            remaining = int(endpoint_wait - now) + 1

            unavailable(
                "This data endpoint is temporarily unavailable.",
                remaining
            )

        # 5. Make exactly ONE request.
        # No automatic retries.
        try:

            response = requests.get(
                BASE_URL + endpoint,
                params=params,
                headers=HEADERS,
                timeout=15
            )

            # Handle rate limiting
            if response.status_code in (418, 429):

                cooldown = get_retry_after(response)

                rate_limit_until = time.time() + cooldown

                stale = get_cached_data(
                    key,
                    allow_stale=True
                )

                if stale is not None:
                    return stale

                unavailable(
                    "CoinGecko rate limit reached. "
                    "Please wait before trying again.",
                    cooldown
                )

            # Handle CoinGecko server errors
            if response.status_code >= 500:

                cooldown = SERVER_ERROR_COOLDOWN

                endpoint_cooldowns[key] = (
                    time.time() + cooldown
                )

                stale = get_cached_data(
                    key,
                    allow_stale=True
                )

                if stale is not None:
                    return stale

                unavailable(
                    "CoinGecko is temporarily experiencing "
                    "server problems.",
                    cooldown
                )

            response.raise_for_status()

            data = response.json()

            # 6. Save successful data
            save_cache(key, data)

            # Clear endpoint cooldown after success
            endpoint_cooldowns.pop(key, None)

            return data

        except requests.exceptions.Timeout:

            cooldown = CONNECTION_ERROR_COOLDOWN

            endpoint_cooldowns[key] = (
                time.time() + cooldown
            )

            stale = get_cached_data(
                key,
                allow_stale=True
            )

            if stale is not None:
                return stale

            unavailable(
                "CoinGecko request timed out.",
                cooldown
            )

        except requests.exceptions.HTTPError as error:

            status = (
                error.response.status_code
                if error.response is not None
                else None
            )

            stale = get_cached_data(
                key,
                allow_stale=True
            )

            if stale is not None:
                return stale

            raise HTTPException(
                status_code=502,
                detail={
                    "message": "CoinGecko returned an HTTP error.",
                    "source": "CoinGecko",
                    "upstream_status": status
                }
            )

        except requests.exceptions.RequestException:

            cooldown = CONNECTION_ERROR_COOLDOWN

            endpoint_cooldowns[key] = (
                time.time() + cooldown
            )

            stale = get_cached_data(
                key,
                allow_stale=True
            )

            if stale is not None:
                return stale

            unavailable(
                "Unable to connect to CoinGecko.",
                cooldown
            )

        except ValueError:

            unavailable(
                "CoinGecko returned invalid JSON data."
            )


# ==================================================
# HOME
# ==================================================
@app.get("/", include_in_schema=False)
def home():
    frontend_file = Path(__file__).resolve().parent / "index.html"

    if not frontend_file.is_file():
        raise HTTPException(
            status_code=500,
            detail="index.html was not found beside main.py"
        )

    return FileResponse(frontend_file)


# ==================================================
# HEALTH CHECK
# ==================================================

@app.get("/health")
def health():

    return {
        "status": "healthy",
        "service": "CRYPTX API"
    }


# ==================================================
# API STATUS
# ==================================================

@app.get("/api/status")
def api_status():

    remaining = max(
        0,
        int(rate_limit_until - time.time())
    )

    return {
        "status": "online",
        "coingecko_cooldown_seconds": remaining,
        "cached_items": len(cache)
    }


# ==================================================
# MARKET DATA
# ==================================================

def get_market_data():

    return get_data(
        key="markets",
        endpoint="/simple/price",
        params={
            "ids": "bitcoin,ethereum,solana",
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }
    )


@app.get("/markets")
def markets():

    return get_market_data()


# ==================================================
# CRYPTO DATA
# ==================================================

@app.get("/crypto")
def crypto_data():

    data = get_market_data()

    return {
        "name": "Bitcoin",
        "symbol": "BTC",
        "price": data["bitcoin"]["usd"],
        "market_status": "Active"
    }


# ==================================================
# MARKET ANALYSIS
# ==================================================

@app.get("/analysis")
def analysis():

    data = get_market_data()

    change = (
        data["bitcoin"].get("usd_24h_change", 0) or 0
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


# ==================================================
# BITCOIN HISTORY
# ==================================================

def get_bitcoin_history():

    data = get_data(
        key="bitcoin_history",
        endpoint="/coins/bitcoin/market_chart",
        params={
            "vs_currency": "usd",
            "days": "1"
        }
    )

    return {
        "prices": data.get("prices", [])
    }


@app.get("/history")
def history():

    return get_bitcoin_history()


@app.get("/portfolio/history")
def portfolio_history():

    return get_bitcoin_history()


@app.get("/portfolio-history")
def portfolio_history_alias():

    return get_bitcoin_history()


# ==================================================
# COMPARISON HISTORY
# ==================================================

@app.get("/comparison-history")
def comparison_history():

    coins = [
        "bitcoin",
        "ethereum",
        "solana"
    ]

    result = {}

    for coin in coins:

        data = get_data(
            key=coin + "_comparison",
            endpoint="/coins/" + coin + "/market_chart",
            params={
                "vs_currency": "usd",
                "days": "1"
            }
        )

        result[coin] = data.get("prices", [])

    return {
        "history": result
    }


# ==================================================
# END OF CRYPTX BACKEND
# ==================================================


