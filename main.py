
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import time

app = FastAPI(
    title="Crypto Intelligence API",
    description="Backend API for Crypto Intelligence Platform",
    version="1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

BASE_URL = "https://api.coingecko.com/api/v3"

# Store API results temporarily
cache = {}


def get_data(key, url, params, cache_seconds):
    current_time = time.time()

    # Return cached data if it is still fresh
    if key in cache:
        saved_time, saved_data = cache[key]

        if current_time - saved_time < cache_seconds:
            return saved_data

    try:
        response = requests.get(
            url,
            params=params,
            timeout=25
        )
        response.raise_for_status()

        data = response.json()

        cache[key] = (current_time, data)

        return data

    except requests.exceptions.RequestException as error:

        # Use older cached data if available
        if key in cache:
            return cache[key][1]

        raise HTTPException(
            status_code=503,
            detail="CoinGecko is temporarily unavailable or rate-limiting requests. Please wait and try again."
        )


@app.get("/")
def home():
    return {"message": "Crypto Intelligence API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/markets")
def markets():

    data = get_data(
        "markets",
        BASE_URL + "/simple/price",
        {
            "ids": "bitcoin,ethereum,solana",
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        },
        120
    )

    return data


@app.get("/crypto")
def crypto_data():

    data = get_data(
        "markets",
        BASE_URL + "/simple/price",
        {
            "ids": "bitcoin,ethereum,solana",
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        },
        120
    )

    return {
        "name": "Bitcoin",
        "symbol": "BTC",
        "price": data["bitcoin"]["usd"],
        "market_status": "Active"
    }


@app.get("/analysis")
def analysis():

    data = markets()

    change = data["bitcoin"].get("usd_24h_change", 0)

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
        "risk_level": risk
    }


@app.get("/history")
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


@app.get("/comparison-history")
def comparison_history():

    coins = ["bitcoin", "ethereum", "solana"]

    result = {}

    for coin in coins:

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
