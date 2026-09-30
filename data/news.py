"""
Headlines for one stock, for your-call decisions. INFORMATIONAL ONLY.

Source order:
  1. Alpha Vantage NEWS_SENTIMENT (headline + bullish/bearish score) if a key is set.
     Free tier ~25 requests/day, so the app fetches only when you open a stock.
  2. Yahoo Finance headlines (free, no key) -- no sentiment score.

Never returns placeholder / made-up headlines. If both sources fail, the result
says so and the list is empty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import yfinance as yf

from data.media_earnings import (
    average_sentiment,
    fetch_news_sentiment_alpha_vantage,
    media_score_label,
)


def _parse_yahoo_time(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def normalise_yahoo_item(item: dict) -> Optional[dict]:
    """Yahoo news items come in two shapes (new: nested under 'content'; old: flat)."""
    content = item.get("content") if isinstance(item.get("content"), dict) else item
    title = content.get("title")
    if not title:
        return None
    provider = content.get("provider") or {}
    url = (content.get("canonicalUrl") or {}).get("url") or content.get("link") or ""
    return {
        "title": title,
        "url": url,
        "source": provider.get("displayName") if isinstance(provider, dict) else content.get("publisher") or "Yahoo",
        "published_at": _parse_yahoo_time(content.get("pubDate") or content.get("providerPublishTime")),
        "summary": (content.get("summary") or "")[:400],
        "sentiment_label": None,
        "sentiment_score": None,
    }


MIN_RELEVANCE = 0.2  # Alpha Vantage relevance of the article to this ticker, 0-1


def keep_relevant(articles: list[dict]) -> list[dict]:
    """Drop articles that only mention the ticker in passing (e.g. bond listings).
    Articles without a relevance score are kept; if nothing passes, keep them all."""
    relevant = [a for a in articles if a.get("relevance") is None or a["relevance"] >= MIN_RELEVANCE]
    return relevant or articles


def fetch_yahoo_headlines(ticker: str, limit: int = 15) -> list[dict]:
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:  # noqa: BLE001
        return []
    items = [normalise_yahoo_item(r) for r in raw if isinstance(r, dict)]
    return [i for i in items if i][:limit]


def get_headlines(ticker: str, alpha_vantage_key: Optional[str] = None, limit: int = 15) -> dict:
    """Return {articles, source, has_sentiment, score_7d, score_30d, badge_7d, note}."""
    note = ""
    if alpha_vantage_key:
        articles, source_note = fetch_news_sentiment_alpha_vantage(ticker, alpha_vantage_key, limit=limit)
        articles = keep_relevant(articles)
        if articles:
            s7, s30 = average_sentiment(articles, 7), average_sentiment(articles, 30)
            return {"articles": articles, "source": "Alpha Vantage (with sentiment)",
                    "has_sentiment": True, "score_7d": s7, "score_30d": s30,
                    "badge_7d": media_score_label(s7) if s7 is not None else "No recent articles",
                    "note": ""}
        note = f"Alpha Vantage returned nothing ({source_note}); showing Yahoo headlines instead."

    articles = fetch_yahoo_headlines(ticker, limit=limit)
    return {"articles": articles, "source": "Yahoo Finance (no sentiment score)",
            "has_sentiment": False, "score_7d": None, "score_30d": None, "badge_7d": None,
            "note": note if articles else (note + " No headlines found.").strip()}
