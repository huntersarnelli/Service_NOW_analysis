"""
Media sentiment & earnings context (INFORMATIONAL ONLY).
========================================================

This module is deliberately decoupled from trading signals / Z-score logic.
Use it for dashboard context today; import into a notebook later if you want
to research or backtest media / earnings features:

    from data.media_earnings import (
        get_ticker_media_earnings,
        get_all_media_earnings_summary,
        media_score_label,
        score_to_sentiment_label,
    )

    # Example notebook workflow
    pack = get_ticker_media_earnings("NOW", api_key=os.getenv("ALPHA_VANTAGE_API_KEY"))
    print(pack["media_score_7d"], pack["next_earnings"])
    pack["articles"]          # recent headlines + sentiment
    pack["sentiment_daily"]   # daily avg score (for charts / backtests)
    pack["earnings_history"]  # EPS estimate / actual / surprise / 1d reaction

Sources
-------
- **Earnings**: yfinance (earnings dates, EPS estimate/actual, surprise %)
- **Media**: Alpha Vantage NEWS_SENTIMENT when ALPHA_VANTAGE_API_KEY is set.
  Without a key, structured *placeholder* data is returned so the UI still
  works. Swap is transparent — same return schema either way.

Extension hooks (for later backtests)
-------------------------------------
- `sentiment_daily` is a date-indexed Series of average ticker sentiment.
  Align it to your price DataFrame with reindex / ffill.
- `earnings_history["reaction_1d_pct"]` is the next-session return after
  the earnings date (Close_t+1 / Close_t - 1). Useful as a simple event study.
- Do NOT feed these into get_levels() unless you intentionally redesign entry rules.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

import numpy as np
import pandas as pd
import yfinance as yf

# ─────────────────────────────────────────────────────────────
# Sentiment taxonomy (Alpha Vantage labels)
# ─────────────────────────────────────────────────────────────
# AV labels use hyphens; we normalize both "Somewhat-Bullish" and "Somewhat Bullish".
LABEL_TO_SCORE: dict[str, float] = {
    "Bearish": -1.0,
    "Somewhat-Bearish": -0.5,
    "Somewhat Bearish": -0.5,
    "Neutral": 0.0,
    "Somewhat-Bullish": 0.5,
    "Somewhat Bullish": 0.5,
    "Bullish": 1.0,
}

CANONICAL_LABELS = [
    "Bearish",
    "Somewhat Bearish",
    "Neutral",
    "Somewhat Bullish",
    "Bullish",
]


def normalize_sentiment_label(label: Optional[str]) -> str:
    """Map API / free-text labels to a stable display label."""
    if not label or not isinstance(label, str):
        return "Neutral"
    cleaned = label.strip().replace("_", " ").replace("-", " ")
    key = cleaned.title()
    # Title-case "Somewhat Bearish" etc.
    mapping = {
        "Bearish": "Bearish",
        "Somewhat Bearish": "Somewhat Bearish",
        "Neutral": "Neutral",
        "Somewhat Bullish": "Somewhat Bullish",
        "Bullish": "Bullish",
    }
    return mapping.get(key, "Neutral")


def score_to_sentiment_label(score: float) -> str:
    """Convert a numeric score in [-1, 1] to a 5-bucket sentiment label."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "Neutral"
    if score <= -0.35:
        return "Bearish"
    if score < -0.15:
        return "Somewhat Bearish"
    if score <= 0.15:
        return "Neutral"
    if score < 0.35:
        return "Somewhat Bullish"
    return "Bullish"


def media_score_label(score: Optional[float]) -> str:
    """
    Coarse badge for dashboard KPIs: Good / Neutral / Bad.

    Thresholds are intentionally simple and documented so you can change
    them later when wiring into research:
      Good    : avg score >  0.15
      Neutral : |avg score| <= 0.15
      Bad     : avg score < -0.15
    """
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "Neutral"
    if score > 0.15:
        return "Good"
    if score < -0.15:
        return "Bad"
    return "Neutral"


def _label_to_score(label: str, fallback_score: Optional[float] = None) -> float:
    if fallback_score is not None and not (
        isinstance(fallback_score, float) and np.isnan(fallback_score)
    ):
        return float(fallback_score)
    norm = normalize_sentiment_label(label)
    # Re-map to LABEL_TO_SCORE keys
    for k, v in LABEL_TO_SCORE.items():
        if normalize_sentiment_label(k) == norm:
            return v
    return 0.0


# ─────────────────────────────────────────────────────────────
# Media / news sentiment
# ─────────────────────────────────────────────────────────────
def _av_request(params: dict[str, str], timeout: int = 20) -> dict:
    """Lightweight Alpha Vantage GET (stdlib only — no extra deps)."""
    url = "https://www.alphavantage.co/query?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "ServiceNowTacticalDashboard/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def fetch_news_sentiment_alpha_vantage(
    ticker: str,
    api_key: str,
    limit: int = 50,
    sort: str = "LATEST",
) -> tuple[list[dict], str]:
    """
    Call Alpha Vantage NEWS_SENTIMENT for one ticker.

    Returns (articles, source_note).
    Each article dict:
      title, url, source, published_at (datetime UTC), summary,
      sentiment_label, sentiment_score, relevance

    Free AV tier is rate-limited (~5 calls/min). Callers should cache.
    """
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker.upper(),
        "sort": sort,
        "limit": str(min(int(limit), 1000)),
        "apikey": api_key,
    }
    try:
        data = _av_request(params)
    except Exception as exc:
        return [], f"Alpha Vantage request failed: {exc}"

    if not data or "feed" not in data:
        note = data.get("Note") or data.get("Information") or data.get("Error Message")
        return [], note or "No NEWS_SENTIMENT feed returned (check API key / rate limit)."

    articles: list[dict] = []
    for item in data.get("feed", [])[:limit]:
        # Prefer ticker-specific sentiment when available
        t_score = None
        t_label = None
        t_rel = None
        for ts in item.get("ticker_sentiment", []) or []:
            if str(ts.get("ticker", "")).upper() == ticker.upper():
                try:
                    t_score = float(ts.get("ticker_sentiment_score"))
                except (TypeError, ValueError):
                    t_score = None
                t_label = ts.get("ticker_sentiment_label")
                try:
                    t_rel = float(ts.get("relevance_score"))
                except (TypeError, ValueError):
                    t_rel = None
                break

        overall_label = item.get("overall_sentiment_label")
        try:
            overall_score = float(item.get("overall_sentiment_score"))
        except (TypeError, ValueError):
            overall_score = None

        label = normalize_sentiment_label(t_label or overall_label)
        score = _label_to_score(label, t_score if t_score is not None else overall_score)

        # AV time format: YYYYMMDDTHHMMSS
        pub_raw = item.get("time_published") or ""
        published_at = _parse_av_time(pub_raw)

        articles.append(
            {
                "title": item.get("title") or "(no title)",
                "url": item.get("url") or "",
                "source": item.get("source") or item.get("source_domain") or "—",
                "published_at": published_at,
                "summary": (item.get("summary") or "")[:400],
                "sentiment_label": label,
                "sentiment_score": score,
                "relevance": t_rel,
            }
        )

    return articles, "Alpha Vantage NEWS_SENTIMENT"


def _parse_av_time(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        # e.g. 20240315T163000
        dt = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None


def _placeholder_articles(ticker: str, n: int = 12) -> list[dict]:
    """
    Deterministic placeholder headlines for UI / offline demos.

    Seeded by ticker so scores are stable across reloads (good for screenshots)
    but differ across names. Replace by setting ALPHA_VANTAGE_API_KEY.
    """
    seed = int(hashlib.md5(ticker.upper().encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)

    templates = [
        ("{t} expands enterprise cloud footprint, analysts note steady demand", "Somewhat Bullish"),
        ("{t} faces mixed options flow ahead of key product event", "Neutral"),
        ("Sector rotation weighs on software names including {t}", "Somewhat Bearish"),
        ("Institutional holders trim stake in {t}, filings show", "Somewhat Bearish"),
        ("{t} partners on AI infrastructure deal — street cautiously optimistic", "Somewhat Bullish"),
        ("Street debate: is {t} priced for perfection?", "Neutral"),
        ("Bull case for {t} centers on durable free-cash-flow growth", "Bullish"),
        ("Short interest ticks higher in {t} after peer guidance cut", "Bearish"),
        ("{t} maintains guidance; management highlights pipeline strength", "Somewhat Bullish"),
        ("Macro risk-off session pressures high-multiple tech, {t} included", "Somewhat Bearish"),
        ("Upgrade: brokerage lifts {t} target on execution consistency", "Bullish"),
        ("{t} remains a core holding for several long-only growth funds", "Neutral"),
    ]

    now = datetime.now(timezone.utc)
    articles: list[dict] = []
    for i in range(n):
        title_tmpl, label = templates[i % len(templates)]
        # Jitter scores around the label center
        base = _label_to_score(label)
        score = float(np.clip(base + rng.normal(0, 0.08), -1, 1))
        label = score_to_sentiment_label(score)
        days_ago = int(rng.integers(0, 45))
        hours_ago = int(rng.integers(0, 24))
        published = now - timedelta(days=days_ago, hours=hours_ago)
        articles.append(
            {
                "title": title_tmpl.format(t=ticker.upper()),
                "url": "",
                "source": "Placeholder Feed",
                "published_at": published,
                "summary": (
                    f"Placeholder article for {ticker.upper()}. "
                    "Set ALPHA_VANTAGE_API_KEY to load live NEWS_SENTIMENT."
                ),
                "sentiment_label": label,
                "sentiment_score": score,
                "relevance": float(rng.uniform(0.3, 0.95)),
            }
        )
    # Newest first
    articles.sort(key=lambda a: a["published_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return articles


def _placeholder_daily_sentiment(ticker: str, days: int = 60) -> pd.Series:
    """Smooth synthetic daily media score series for charts when no live feed."""
    seed = int(hashlib.md5(f"{ticker}-daily".encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp.utcnow().normalize(), periods=days, freq="D")
    # Mean-reverting AR(1)-ish path centered near mild positive / mixed
    center = float(rng.uniform(-0.1, 0.2))
    vals = []
    x = center
    for _ in range(days):
        x = 0.85 * x + 0.15 * center + float(rng.normal(0, 0.06))
        vals.append(float(np.clip(x, -1, 1)))
    return pd.Series(vals, index=idx, name="media_score")


def articles_to_daily_sentiment(
    articles: list[dict],
    days: int = 60,
) -> pd.Series:
    """
    Bin article scores by UTC date and average — research-friendly daily series.

    Days with no articles are left as NaN (do not ffill here so backtests can
    choose their own fill policy).
    """
    end = pd.Timestamp.utcnow().normalize()
    idx = pd.date_range(end=end, periods=days, freq="D")
    if not articles:
        return pd.Series(np.nan, index=idx, name="media_score")

    rows = []
    for a in articles:
        pub = a.get("published_at")
        if pub is None:
            continue
        if getattr(pub, "tzinfo", None) is not None:
            day = pd.Timestamp(pub).tz_convert("UTC").normalize().tz_localize(None)
        else:
            day = pd.Timestamp(pub).normalize()
        rows.append({"date": day, "score": a.get("sentiment_score", 0.0)})

    if not rows:
        return pd.Series(np.nan, index=idx, name="media_score")

    adf = pd.DataFrame(rows)
    daily = adf.groupby("date")["score"].mean()
    # Align to full calendar window
    daily.index = pd.DatetimeIndex(daily.index).tz_localize(None)
    out = daily.reindex(idx)
    out.name = "media_score"
    return out


def average_sentiment(
    articles: list[dict],
    lookback_days: int,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """Mean sentiment_score of articles published within lookback_days."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    scores = []
    for a in articles:
        pub = a.get("published_at")
        if pub is None:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub >= cutoff:
            sc = a.get("sentiment_score")
            if sc is not None and not (isinstance(sc, float) and np.isnan(sc)):
                scores.append(float(sc))
    if not scores:
        return None
    return float(np.mean(scores))


def fetch_media_bundle(
    ticker: str,
    api_key: Optional[str] = None,
    article_limit: int = 40,
    trend_days: int = 60,
) -> dict[str, Any]:
    """
    Full media package for one ticker.

    Returns dict with:
      articles, sentiment_daily, media_score_7d, media_score_30d,
      media_badge_7d, media_badge_30d, source, is_placeholder
    """
    key = (api_key or os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip()
    is_placeholder = False

    if key:
        articles, source = fetch_news_sentiment_alpha_vantage(
            ticker, api_key=key, limit=article_limit
        )
        if not articles:
            # Fall back so the tab still shows something useful
            articles = _placeholder_articles(ticker)
            is_placeholder = True
            source = f"Placeholder (live feed empty: {source})"
            sentiment_daily = _placeholder_daily_sentiment(ticker, days=trend_days)
        else:
            sentiment_daily = articles_to_daily_sentiment(articles, days=trend_days)
            # If articles only cover a few days, optional: blend is not done —
            # leave sparse history honest for research.
    else:
        articles = _placeholder_articles(ticker)
        sentiment_daily = _placeholder_daily_sentiment(ticker, days=trend_days)
        source = "Placeholder (set ALPHA_VANTAGE_API_KEY for live NEWS_SENTIMENT)"
        is_placeholder = True

    score_7d = average_sentiment(articles, 7)
    score_30d = average_sentiment(articles, 30)

    # If article window is sparse, fall back to daily series means
    if score_7d is None and sentiment_daily is not None:
        tail = sentiment_daily.dropna().tail(7)
        score_7d = float(tail.mean()) if len(tail) else None
    if score_30d is None and sentiment_daily is not None:
        tail = sentiment_daily.dropna().tail(30)
        score_30d = float(tail.mean()) if len(tail) else None

    return {
        "ticker": ticker.upper(),
        "articles": articles,
        "sentiment_daily": sentiment_daily,
        "media_score_7d": score_7d,
        "media_score_30d": score_30d,
        "media_badge_7d": media_score_label(score_7d),
        "media_badge_30d": media_score_label(score_30d),
        "source": source,
        "is_placeholder": is_placeholder,
    }


# ─────────────────────────────────────────────────────────────
# Earnings (yfinance)
# ─────────────────────────────────────────────────────────────
def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        if pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _earnings_reaction_1d(
    ticker: str,
    earnings_dates: list[pd.Timestamp],
    price_lookback_days: int = 400,
) -> dict[pd.Timestamp, Optional[float]]:
    """
    1-day stock reaction after each earnings date.

    Definition (documented for backtests):
        reaction = Close[next trading day after earnings] / Close[earnings day] - 1
    If the earnings timestamp is after the close, yfinance dates are usually
    calendar dates; we use asof logic on the daily bar index.

    Returns map of normalized date -> reaction fraction (e.g. 0.02 = +2%).
    """
    if not earnings_dates:
        return {}

    end = datetime.now().date() + timedelta(days=1)
    start = end - timedelta(days=price_lookback_days)
    try:
        px = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        return {}

    if px is None or px.empty or "Close" not in px.columns:
        return {}

    closes = px["Close"].copy()
    closes.index = pd.DatetimeIndex(closes.index).tz_localize(None).normalize()
    closes = closes[~closes.index.duplicated(keep="last")].sort_index()

    out: dict[pd.Timestamp, Optional[float]] = {}
    for ed in earnings_dates:
        ed_n = pd.Timestamp(ed).tz_localize(None).normalize() if pd.notna(ed) else None
        if ed_n is None:
            continue
        # Find earnings session: on or before ed_n
        if ed_n in closes.index:
            i = closes.index.get_loc(ed_n)
        else:
            pos = closes.index.searchsorted(ed_n, side="right") - 1
            if pos < 0:
                out[ed_n] = None
                continue
            i = pos
        if isinstance(i, slice):
            i = i.start
        if i is None or i >= len(closes) - 1:
            out[ed_n] = None
            continue
        c0 = float(closes.iloc[i])
        c1 = float(closes.iloc[i + 1])
        if c0 == 0 or np.isnan(c0) or np.isnan(c1):
            out[ed_n] = None
        else:
            out[ed_n] = c1 / c0 - 1.0
    return out


def _beat_miss_from_surprise(sur: Optional[float], rep: Optional[float], est: Optional[float]) -> str:
    if sur is not None and sur > 0.05:
        return "Beat"
    if sur is not None and sur < -0.05:
        return "Miss"
    if sur is not None:
        return "Inline"
    if rep is not None and est is not None:
        if rep > est:
            return "Beat"
        if rep < est:
            return "Miss"
        return "Inline"
    return "—"


def _history_from_earnings_dates(
    ticker: str,
    ed_df: pd.DataFrame,
    history_limit: int,
    next_earnings: Optional[pd.Timestamp],
) -> tuple[list[dict], Optional[pd.Timestamp]]:
    """Parse yfinance get_earnings_dates / earnings_dates tables."""
    df = ed_df.copy()
    colmap = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if "eps estimate" in cl:
            colmap[c] = "EPS Estimate"
        elif "reported eps" in cl:
            colmap[c] = "Reported EPS"
        elif "surprise" in cl:
            colmap[c] = "Surprise %"
    df = df.rename(columns=colmap)

    dates = [_coerce_date(idx_val) for idx_val in df.index]
    reactions = _earnings_reaction_1d(ticker, [d for d in dates if d is not None])
    today = pd.Timestamp.utcnow().normalize().tz_localize(None)
    hist_rows: list[dict] = []

    for i, (idx_val, row) in enumerate(df.iterrows()):
        ed = dates[i] if i < len(dates) else _coerce_date(idx_val)
        est = _safe_float(row["EPS Estimate"]) if "EPS Estimate" in df.columns else None
        rep = _safe_float(row["Reported EPS"]) if "Reported EPS" in df.columns else None
        sur = _safe_float(row["Surprise %"]) if "Surprise %" in df.columns else None

        # get_earnings_dates Surprise(%) is typically already in percent units
        if sur is None and est is not None and rep is not None and est != 0:
            sur = (rep - est) / abs(est) * 100.0

        ed_key = pd.Timestamp(ed).normalize() if ed is not None else None
        rx = reactions.get(ed_key) if ed_key is not None else None

        hist_rows.append(
            {
                "Earnings Date": ed,
                "EPS Estimate": est,
                "Reported EPS": rep,
                "Surprise %": sur,
                "Beat/Miss": _beat_miss_from_surprise(sur, rep, est),
                "Reaction 1D %": (rx * 100.0) if rx is not None else None,
            }
        )

        if next_earnings is None and ed is not None:
            ed_n = pd.Timestamp(ed).normalize()
            if ed_n >= today and rep is None:
                next_earnings = ed_n

    hist_rows.sort(key=lambda r: r["Earnings Date"] or pd.Timestamp.min, reverse=True)
    return hist_rows[:history_limit], next_earnings


def _history_from_quarterly_earnings(
    ticker: str,
    q_df: pd.DataFrame,
    history_limit: int,
) -> list[dict]:
    """
    Fallback when earnings announcement dates are unavailable (e.g. missing lxml).

    yfinance Ticker.earnings_history uses quarter-end dates and stores
    surprisePercent as a *fraction* (0.14 ≈ 14%). Documented so notebook
    users know this is not the official announcement date.
    """
    df = q_df.copy()
    # Normalize columns
    rename = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in ("epsestimate", "eps estimate"):
            rename[c] = "epsEstimate"
        elif cl in ("epsactual", "eps actual", "reported eps"):
            rename[c] = "epsActual"
        elif cl in ("surprisepercent", "surprise percent", "surprise%"):
            rename[c] = "surprisePercent"
    df = df.rename(columns=rename)

    dates = [_coerce_date(i) for i in df.index]
    reactions = _earnings_reaction_1d(ticker, [d for d in dates if d is not None])
    rows: list[dict] = []
    for i, (_, row) in enumerate(df.iterrows()):
        ed = dates[i] if i < len(dates) else None
        est = _safe_float(row["epsEstimate"]) if "epsEstimate" in df.columns else None
        rep = _safe_float(row["epsActual"]) if "epsActual" in df.columns else None
        sur_frac = _safe_float(row["surprisePercent"]) if "surprisePercent" in df.columns else None
        # Convert fraction → percent for display consistency with get_earnings_dates
        sur = sur_frac * 100.0 if sur_frac is not None else None
        if sur is None and est is not None and rep is not None and est != 0:
            sur = (rep - est) / abs(est) * 100.0

        ed_key = pd.Timestamp(ed).normalize() if ed is not None else None
        rx = reactions.get(ed_key) if ed_key is not None else None
        rows.append(
            {
                "Earnings Date": ed,
                "EPS Estimate": est,
                "Reported EPS": rep,
                "Surprise %": sur,
                "Beat/Miss": _beat_miss_from_surprise(sur, rep, est),
                "Reaction 1D %": (rx * 100.0) if rx is not None else None,
            }
        )
    rows.sort(key=lambda r: r["Earnings Date"] or pd.Timestamp.min, reverse=True)
    return rows[:history_limit]


def fetch_earnings_bundle(ticker: str, history_limit: int = 12) -> dict[str, Any]:
    """
    Upcoming earnings date + historical EPS table via yfinance.

    Returns:
      next_earnings: date | None
      earnings_history: DataFrame with columns
        Earnings Date, EPS Estimate, Reported EPS, Surprise %,
        Beat/Miss, Reaction 1D %
      source: str
      history_note: optional note about date semantics
    """
    t = yf.Ticker(ticker)
    next_earnings: Optional[pd.Timestamp] = None
    hist_rows: list[dict] = []
    history_note = ""
    source = "yfinance"

    # --- Upcoming date (calendar is a dict on recent yfinance) ---
    try:
        cal = t.calendar
        if isinstance(cal, pd.DataFrame) and not cal.empty:
            for key in ("Earnings Date", "EarningsDate"):
                if key in cal.index:
                    val = cal.loc[key].iloc[0] if hasattr(cal.loc[key], "iloc") else cal.loc[key]
                    next_earnings = _coerce_date(val)
                    break
                if key in cal.columns:
                    next_earnings = _coerce_date(cal[key].iloc[0])
                    break
        elif isinstance(cal, dict):
            for key in ("Earnings Date", "EarningsDate", "earningsDate"):
                if key in cal:
                    val = cal[key]
                    if isinstance(val, (list, tuple)) and val:
                        val = val[0]
                    next_earnings = _coerce_date(val)
                    break
    except Exception:
        pass

    # --- Preferred: announcement-date history (needs lxml on some installs) ---
    ed_df = None
    try:
        if hasattr(t, "get_earnings_dates"):
            ed_df = t.get_earnings_dates(limit=history_limit)
        if (ed_df is None or getattr(ed_df, "empty", True)) and hasattr(t, "earnings_dates"):
            ed_df = t.earnings_dates
    except Exception:
        ed_df = None

    if ed_df is not None and not getattr(ed_df, "empty", True):
        hist_rows, next_earnings = _history_from_earnings_dates(
            ticker, ed_df, history_limit, next_earnings
        )
        source = "yfinance (earnings dates)"
    else:
        # --- Fallback: quarterly earnings_history ---
        try:
            q = getattr(t, "earnings_history", None)
            if q is not None and isinstance(q, pd.DataFrame) and not q.empty:
                hist_rows = _history_from_quarterly_earnings(ticker, q, history_limit)
                source = "yfinance (quarterly earnings_history)"
                history_note = (
                    "Announcement dates unavailable; showing quarter-end EPS history. "
                    "Install lxml for full earnings-date tables: pip install lxml"
                )
        except Exception:
            pass

    history = (
        pd.DataFrame(hist_rows)
        if hist_rows
        else pd.DataFrame(
            columns=[
                "Earnings Date",
                "EPS Estimate",
                "Reported EPS",
                "Surprise %",
                "Beat/Miss",
                "Reaction 1D %",
            ]
        )
    )

    return {
        "ticker": ticker.upper(),
        "next_earnings": next_earnings,
        "earnings_history": history,
        "source": source,
        "history_note": history_note,
    }


def _coerce_date(val: Any) -> Optional[pd.Timestamp]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (list, tuple)):
        if not val:
            return None
        val = val[0]
    try:
        ts = pd.Timestamp(val)
        if pd.isna(ts):
            return None
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return ts
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Combined package (what the dashboard tab consumes)
# ─────────────────────────────────────────────────────────────
def get_ticker_media_earnings(
    ticker: str,
    api_key: Optional[str] = None,
    article_limit: int = 40,
    trend_days: int = 60,
    earnings_limit: int = 12,
) -> dict[str, Any]:
    """
    Combined media + earnings pack for one ticker.

    Safe to call from Streamlit (wrap with st.cache_data) or notebooks.
    """
    media = fetch_media_bundle(
        ticker,
        api_key=api_key,
        article_limit=article_limit,
        trend_days=trend_days,
    )
    earnings = fetch_earnings_bundle(ticker, history_limit=earnings_limit)

    # Days until next earnings (None if unknown)
    days_to_earn = None
    ne = earnings.get("next_earnings")
    if ne is not None:
        today = pd.Timestamp.utcnow().normalize().tz_localize(None)
        ne_n = pd.Timestamp(ne).normalize()
        days_to_earn = int((ne_n - today).days)

    # Last reported beat/miss for summary table
    last_beat = "—"
    last_surprise = None
    hist: pd.DataFrame = earnings.get("earnings_history")
    if hist is not None and not hist.empty:
        reported = hist[hist["Reported EPS"].notna()] if "Reported EPS" in hist.columns else hist
        if not reported.empty:
            last_beat = reported.iloc[0].get("Beat/Miss", "—")
            last_surprise = reported.iloc[0].get("Surprise %")

    return {
        **media,
        "next_earnings": earnings.get("next_earnings"),
        "days_to_earnings": days_to_earn,
        "earnings_history": earnings.get("earnings_history"),
        "earnings_source": earnings.get("source"),
        "earnings_history_note": earnings.get("history_note") or "",
        "last_beat_miss": last_beat,
        "last_surprise_pct": last_surprise,
    }


def get_all_media_earnings_summary(
    tickers: list[str],
    api_key: Optional[str] = None,
    sleep_between_av: float = 0.0,
) -> pd.DataFrame:
    """
    One-row-per-ticker summary for the main Media & Earnings table.

    Parameters
    ----------
    sleep_between_av :
        Optional pause between tickers when using a free Alpha Vantage key
        (e.g. 12.0 for ~5 calls/min). Ignored for placeholders.
    """
    records = []
    key = (api_key or os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip()

    for i, t in enumerate(tickers):
        if i > 0 and key and sleep_between_av > 0:
            time.sleep(sleep_between_av)
        try:
            pack = get_ticker_media_earnings(t, api_key=api_key)
        except Exception as exc:
            records.append(
                {
                    "Ticker": t,
                    "Media 7D": None,
                    "Media Badge 7D": "Neutral",
                    "Media 30D": None,
                    "Media Badge 30D": "Neutral",
                    "Next Earnings": None,
                    "Days to Earnings": None,
                    "Last Beat/Miss": "—",
                    "Last Surprise %": None,
                    "Source": f"Error: {exc}",
                    "Placeholder": True,
                }
            )
            continue

        ne = pack.get("next_earnings")
        records.append(
            {
                "Ticker": pack["ticker"],
                "Media 7D": pack.get("media_score_7d"),
                "Media Badge 7D": pack.get("media_badge_7d"),
                "Media 30D": pack.get("media_score_30d"),
                "Media Badge 30D": pack.get("media_badge_30d"),
                "Next Earnings": pd.Timestamp(ne).date() if ne is not None else None,
                "Days to Earnings": pack.get("days_to_earnings"),
                "Last Beat/Miss": pack.get("last_beat_miss"),
                "Last Surprise %": pack.get("last_surprise_pct"),
                "Source": pack.get("source"),
                "Placeholder": pack.get("is_placeholder", False),
            }
        )
    return pd.DataFrame(records)
