# Dual-Mode Tactical Trading System — Live Dashboard

Streamlit dashboard for the dual-mode mean-reversion strategy covering ServiceNow and related names.

## Strategy (exact logic)

| Bucket | Tickers | Entry |
|--------|---------|--------|
| **Momentum** | NVDA, META, NET | Z-score &lt; −1.5 (no trend filter) |
| **Quality** | NOW, MSFT, GOOGL, PANW, CRWD, DDOG, CRM | Z-score &lt; −1.5 **and** Close &gt; 50-SMA |

- **Buy trigger** = 20-SMA + (−1.5 × rolling std)
- **Initial stop** (if buy at trigger) = trigger − 2×ATR
- **Trailing stop** = Close − 2×ATR (only raised)
- **Exit** = trailing stop hit **or** Z-score &gt; 0 (mean reversion)

All thresholds (Z, ATR mult, trend SMA length, capital) are adjustable in the sidebar.

## Requirements

- Python 3.10+
- Internet access (yfinance / Yahoo Finance)

## Install & run

```bash
# From this folder
cd path/to/Service_NOW_analysis

# Optional but recommended: virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser (default `http://localhost:8501`).

### One-liner (after install)

```bash
streamlit run app.py
```

## Dashboard tabs

1. **Overview** — Full scanner for both buckets, BUY / NEAR highlights, deep-dive card
2. **Momentum Bucket** — NVDA, META, NET (no filter)
3. **Quality Bucket** — NOW and quality names (mild 50-SMA filter)
4. **Filter Compare** — Side-by-side with vs without trend filter for any ticker
5. **Rules** — Written strategy reference + formulas

## Features

- Live price, Z-score, 20-SMA, ATR, 50-SMA
- Buy trigger, initial stop, mean-reversion exit, R:R to SMA
- Distance to trigger in $ and %
- Color-coded **BUY SIGNAL** / NEAR / WATCH
- 1% risk position-size hint from sidebar capital
- Price + Z-score charts (Plotly)
- Manual refresh + optional 60s auto-refresh
- Dark/light friendly (follows Streamlit theme)

## Notes

- Data is cached for ~60 seconds; use **Refresh data now** for a hard reload.
- This app does **not** place trades or connect to a broker.
- For research / educational use only — not investment advice.
