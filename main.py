
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
# =================================
