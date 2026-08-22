"""
Overreaction event study — library.

Question this answers
---------------------
STRATEGY_REVIEW.md establishes that the Z<-1.2 entry beats random (§5.12) but
that the *depth* of the dip is irrelevant (§5.4). That leaves an obvious gap:
Z measures the MAGNITUDE of a move and says nothing about its CAUSE.

The academic literature says cause is what matters:

  Chan (2003), "Stock Price Reaction to News and No-News"
  Savor (2012), "Stock Returns After Major Price Shocks"
      -> big moves WITH public news CONTINUE (drift)
      -> big moves WITHOUT news REVERSE (overreaction)

  Bernard & Thomas (1989), post-earnings announcement drift
      -> prices UNDER-react to earnings surprises; drift runs 60-90 days
         in the direction of the surprise

If that holds on this universe, then buying a dip that follows an earnings
miss is buying into a negative drift, and the live dashboard's rule of sizing
UP to 35% within 10 days after earnings is backwards.

This module tags every dip event with proxies for "was there news?" and
measures forward returns by cohort.

Event definition
----------------
A dip event is the bar on which Z(20) CROSSES DOWN through z_entry. Crossings
are used rather than every qualifying bar so that one decline contributes one
observation; `every_bar` would count a single 5-day slide five times and
badly overstate the sample size.

Tags computed on the event bar
------------------------------
vol_ratio     Volume / median(Volume, 20d). The news proxy that needs no news
              data: information arrives with volume, noise does not.
gap_atr       (Close_t - Close_{t-1}) / ATR14_{t-1}. Shock size, distinct from
              Z(20), which measures position rather than the jump.
idio_z        Z(20) computed on a MARKET-NEUTRALISED price index. Separates
              "this name overreacted" from "everything fell 3% today".
                beta_t   rolling 120d OLS beta of the name on SPY
                resid_t  r_name - beta_t * r_spy
                R_t      cumulative residual index
                idio_z   (R - SMA20(R)) / sd20(R)
breadth       Fraction of the universe simultaneously below z_entry that day.
              High breadth = market event, not a single-name overreaction.
days_since_earnings  Trading days since the most recent earnings report.
eps_surprise_pct     Reported surprise % of that report (signed).

Forward returns
---------------
Raw and market-excess (minus SPY over the identical span) at 5/20/60/120
trading days. Excess is the one to read: raw returns are contaminated by
where in the market cycle the cohort's events happened to cluster.

Inference
---------
Events overlap in time and cluster across names, so a naive t-test on the
event panel treats correlated observations as independent and overstates
significance badly. `monthly_tstat` collapses the panel to one mean per
calendar month first, then tests that series. That is a coarse but honest
cluster-robust correction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "studies" / ".cache_overreaction"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TRADING_DAYS = 252
HORIZONS = (5, 20, 60, 120)


# ─────────────────────────────────────────────────────────────
# Universe
# ─────────────────────────────────────────────────────────────
# ~120 liquid US names, $20B+, deliberately spanning mega / large / mid and
# several sectors. Includes names that did BADLY over the window (INTC, PYPL,
# WBA, DIS, NKE, MRNA, ZM, DOCU) so the basket is not a list of winners.
# Survivorship is still not fully modelled -- these are names listed today --
# and that caveat is repeated in the writeup.
UNIVERSE = [
    # mega tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    # large tech / semis
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "ADI",
    "NXPI", "MRVL", "ON", "SWKS", "TER",
    # software / internet
    "NOW", "PANW", "CRWD", "DDOG", "NET", "SNOW", "MDB", "ZS", "TEAM", "WDAY",
    "SHOP", "UBER", "ABNB", "PYPL", "INTU", "ADSK", "CDNS", "SNPS",
    "FTNT", "OKTA", "TWLO", "DOCU", "ZM", "ROKU", "PINS", "SNAP", "SPOT", "EBAY",
    # payments / financials
    "V", "MA", "AXP", "JPM", "BAC", "GS", "MS", "SCHW", "BLK", "SPGI",
    "COIN", "HOOD",
    # healthcare / pharma
    "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "DHR", "ISRG", "VRTX",
    "REGN", "AMGN", "GILD", "MRNA", "BIIB", "CVS", "ZTS", "SYK", "BSX", "MDT",
    # consumer
    "WMT", "COST", "HD", "LOW", "TGT", "NKE", "SBUX", "MCD", "PG", "KO",
    "PEP", "DIS", "NFLX", "CMG", "LULU", "WBA", "DG", "ULTA", "YUM", "MAR",
    # industrials / energy / other
    "CAT", "DE", "BA", "HON", "GE", "UPS", "FDX", "LMT", "RTX", "UNP",
    "XOM", "CVX", "COP", "SLB", "OXY", "NEE", "DUK", "LIN", "APD", "SHW",
]

BENCHMARK = "SPY"


# ─────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────
def load_prices(tickers, start: str, end: str) -> dict[str, pd.DataFrame]:
    """Batched OHLCV download with an on-disk parquet cache."""
    tickers = list(dict.fromkeys(tickers))
    out: dict[str, pd.DataFrame] = {}
    todo = []
    for t in tickers:
        p = CACHE_DIR / f"px_{t}_{start}_{end}.parquet"
        if p.exists():
            try:
                out[t] = pd.read_parquet(p)
                continue
            except Exception:
                pass
        todo.append(t)

    if todo:
        # chunk so a single bad ticker cannot poison the whole request
        for i in range(0, len(todo), 40):
            chunk = todo[i: i + 40]
            raw = yf.download(
                chunk, start=start, end=end, group_by="ticker",
                auto_adjust=True, threads=True, progress=False,
            )
            multi = isinstance(raw.columns, pd.MultiIndex)
            for t in chunk:
                try:
                    df = (raw[t] if multi else raw).copy()
                except KeyError:
                    continue
                df = df.dropna(subset=["Close"])
                if len(df) < 300:
                    continue
                df.index = pd.to_datetime(df.index)
                if getattr(df.index, "tz", None) is not None:
                    df.index = df.index.tz_localize(None)
                out[t] = df
                try:
                    df.to_parquet(CACHE_DIR / f"px_{t}_{start}_{end}.parquet")
                except Exception:
                    pass
    return out


def load_earnings(tickers) -> dict[str, pd.DataFrame]:
    """
    Per-ticker earnings dates + EPS surprise, cached to disk.

    yfinance returns roughly 12 years of history here, which is deeper than
    STRATEGY_REVIEW.md §5.32 assumed. Timestamps are dropped to naive dates;
    an after-close report is attributed to the NEXT trading bar, which is
    when the price actually moves.
    """
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        p = CACHE_DIR / f"earn_{t}.parquet"
        if p.exists():
            try:
                out[t] = pd.read_parquet(p)
                continue
            except Exception:
                pass
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=80)
        except Exception:
            ed = None
        if ed is None or len(ed) == 0:
            df = pd.DataFrame(columns=["date", "surprise_pct", "after_close"])
        else:
            idx = ed.index
            df = pd.DataFrame({
                "date": pd.to_datetime([d.tz_localize(None).normalize() for d in idx]),
                "surprise_pct": pd.to_numeric(
                    ed.get("Surprise(%)", pd.Series(index=idx, dtype=float)).values,
                    errors="coerce",
                ),
                "after_close": np.asarray(idx.hour) >= 12,
            })
            df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        out[t] = df
        try:
            df.to_parquet(p)
        except Exception:
            pass
    return out


# ─────────────────────────────────────────────────────────────
# Indicators
# ─────────────────────────────────────────────────────────────
def add_indicators(
    df: pd.DataFrame,
    spy: pd.DataFrame,
    sma_window: int = 20,
    atr_window: int = 14,
    beta_window: int = 120,
) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]

    d["ret"] = c.pct_change()
    d["sma"] = c.rolling(sma_window).mean()
    d["sd"] = c.rolling(sma_window).std()
    d["z"] = (c - d["sma"]) / d["sd"]

    pc = c.shift(1)
    tr = pd.concat(
        [d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()],
        axis=1,
    ).max(axis=1)
    d["atr"] = tr.rolling(atr_window).mean()

    # shock size on the event bar, measured in yesterday's ATR
    d["gap_atr"] = (c - pc) / d["atr"].shift(1)

    # volume relative to its own recent median (median resists earnings spikes)
    d["vol_ratio"] = d["Volume"] / d["Volume"].rolling(20).median()

    # ---- market-neutralised (idiosyncratic) Z ------------------------------
    # Rolling 120d beta on SPY, residual return, cumulative residual index,
    # then the same Z(20) construction applied to that index.
    m = spy["Close"].pct_change().reindex(d.index)
    cov = d["ret"].rolling(beta_window).cov(m)
    var = m.rolling(beta_window).var()
    beta = (cov / var).clip(-3, 3)
    d["beta"] = beta
    resid = d["ret"] - beta * m
    ridx = resid.fillna(0.0).cumsum()
    d["idio_z"] = (ridx - ridx.rolling(sma_window).mean()) / ridx.rolling(sma_window).std()

    # ---- ex-ante conditioning variables ------------------------------------
    # Everything below is observable on the event bar and is a candidate for
    # the conditional-sizing model in run_optimisation_study.py. Nothing here
    # may depend on the name's own realised performance, which is the
    # selection-bias trap STRATEGY_REVIEW.md §5.7 documents.
    d["rvol20"] = d["ret"].rolling(20).std() * np.sqrt(TRADING_DAYS) * 100
    d["log_dollar_vol"] = np.log(
        (d["Close"] * d["Volume"]).rolling(20).median().clip(lower=1.0)
    )
    d["dist_52w"] = (c / c.rolling(252).max() - 1.0) * 100

    return d


def attach_earnings(d: pd.DataFrame, earn: pd.DataFrame) -> pd.DataFrame:
    """
    days_since_earnings / eps_surprise_pct for the most recent report at or
    before each bar. An after-close report is shifted to the next bar so the
    reaction bar is the one that gets days_since == 0.
    """
    d = d.copy()
    d["days_since_earnings"] = np.nan
    d["eps_surprise_pct"] = np.nan
    if earn is None or len(earn) == 0:
        return d

    idx = d.index
    for _, row in earn.sort_values("date").iterrows():
        ed = row["date"]
        if pd.isna(ed):
            continue
        # reaction bar = first trading bar strictly after an after-close report,
        # or the report bar itself for a pre-open report
        if bool(row.get("after_close", True)):
            pos = idx.searchsorted(ed, side="right")
        else:
            pos = idx.searchsorted(ed, side="left")
        if pos >= len(idx):
            continue
        ahead = idx[pos:]
        # each later report overwrites from its own reaction bar onward, so
        # every bar ends up carrying its most recent report
        d.loc[ahead, "days_since_earnings"] = np.arange(len(ahead))
        d.loc[ahead, "eps_surprise_pct"] = row.get("surprise_pct", np.nan)
    return d


# ─────────────────────────────────────────────────────────────
# Event extraction
# ─────────────────────────────────────────────────────────────
def extract_events(
    frames: dict[str, pd.DataFrame],
    z_entry: float = -1.2,
    horizons=HORIZONS,
    start: Optional[str] = None,
) -> pd.DataFrame:
    """One row per Z-crossing, tagged, with forward raw and excess returns."""
    # breadth: share of names below the threshold each day
    zpanel = pd.DataFrame({t: d["z"] for t, d in frames.items() if t != BENCHMARK})
    breadth = (zpanel < z_entry).sum(axis=1) / zpanel.notna().sum(axis=1)

    spy_close = frames[BENCHMARK]["Close"]
    rows = []

    for t, d in frames.items():
        if t == BENCHMARK:
            continue
        z = d["z"]
        cross = (z < z_entry) & (z.shift(1) >= z_entry)
        cross = cross.fillna(False)
        if start is not None:
            cross &= d.index >= pd.Timestamp(start)
        ev_idx = d.index[cross]
        if len(ev_idx) == 0:
            continue

        c = d["Close"]
        spy_al = spy_close.reindex(d.index).ffill()

        for dt in ev_idx:
            i = d.index.get_loc(dt)
            r = {
                "ticker": t,
                "date": dt,
                "close": float(c.iloc[i]),
                "z": float(z.iloc[i]),
                "idio_z": _f(d["idio_z"].iloc[i]),
                "vol_ratio": _f(d["vol_ratio"].iloc[i]),
                "gap_atr": _f(d["gap_atr"].iloc[i]),
                "beta": _f(d["beta"].iloc[i]),
                "breadth": float(breadth.get(dt, np.nan)),
                "days_since_earnings": _f(d["days_since_earnings"].iloc[i]),
                "eps_surprise_pct": _f(d["eps_surprise_pct"].iloc[i]),
                "rvol20": _f(d["rvol20"].iloc[i]),
                "log_dollar_vol": _f(d["log_dollar_vol"].iloc[i]),
                "dist_52w": _f(d["dist_52w"].iloc[i]),
            }
            for h in horizons:
                j = i + h
                if j < len(d):
                    fwd = float(c.iloc[j] / c.iloc[i] - 1.0)
                    mkt = float(spy_al.iloc[j] / spy_al.iloc[i] - 1.0)
                    r[f"fwd_{h}"] = fwd * 100
                    r[f"exc_{h}"] = (fwd - mkt) * 100
                else:
                    r[f"fwd_{h}"] = np.nan
                    r[f"exc_{h}"] = np.nan
            rows.append(r)

    ev = pd.DataFrame(rows).sort_values(["date", "ticker"]).reset_index(drop=True)
    ev["month"] = ev["date"].dt.to_period("M").astype(str)
    ev["year"] = ev["date"].dt.year
    return ev


def _f(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return np.nan
    return v if np.isfinite(v) else np.nan


# ─────────────────────────────────────────────────────────────
# Inference
# ─────────────────────────────────────────────────────────────
def monthly_tstat(ev: pd.DataFrame, col: str) -> dict:
    """
    Cluster-robust-ish t-stat: collapse to one mean per calendar month, then
    t-test that series against zero. Dip events cluster hard in time (a market
    selloff prints dozens the same week), so the raw event count is nowhere
    near the effective sample size.
    """
    empty = {"n": 0, "n_months": 0, "mean": np.nan, "median": np.nan,
             "sd_monthly": np.nan, "t": np.nan, "ci_lo": np.nan,
             "ci_hi": np.nan, "hit_rate": np.nan}
    if col not in ev.columns:
        return empty
    s = ev.dropna(subset=[col])
    if s.empty:
        return empty
    monthly = s.groupby("month")[col].mean()
    n = len(monthly)
    mu = float(monthly.mean())
    sd = float(monthly.std(ddof=1)) if n > 1 else np.nan
    se = sd / np.sqrt(n) if n > 1 and sd > 0 else np.nan
    t = mu / se if se and np.isfinite(se) and se > 0 else np.nan
    return {
        "n": int(len(s)),
        "n_months": int(n),
        "mean": mu,
        "median": float(s[col].median()),
        "sd_monthly": sd,
        "t": float(t) if pd.notna(t) else np.nan,
        "ci_lo": float(mu - 1.96 * se) if pd.notna(se) else np.nan,
        "ci_hi": float(mu + 1.96 * se) if pd.notna(se) else np.nan,
        "hit_rate": float((s[col] > 0).mean() * 100),
    }


def cohort_table(ev: pd.DataFrame, label_col: str, horizons=HORIZONS) -> pd.DataFrame:
    """Mean excess return by cohort at each horizon, with monthly t-stats."""
    rows = []
    for name, grp in ev.groupby(label_col, observed=True):
        r = {"cohort": str(name), "n": len(grp)}
        for h in horizons:
            st = monthly_tstat(grp, f"exc_{h}")
            r[f"exc_{h}"] = st["mean"]
            r[f"t_{h}"] = st["t"]
            r[f"hit_{h}"] = st["hit_rate"]
        rows.append(r)
    return pd.DataFrame(rows)


def diff_test(ev: pd.DataFrame, mask_a: pd.Series, mask_b: pd.Series,
              col: str, label: str) -> dict:
    """
    Difference in monthly means between two cohorts, paired by month so the
    common market factor cancels. This is the test that matters: cohort A
    minus cohort B in the same month removes the shared beta.
    """
    a = ev[mask_a].dropna(subset=[col])
    b = ev[mask_b].dropna(subset=[col])
    ma = a.groupby("month")[col].mean()
    mb = b.groupby("month")[col].mean()
    joined = pd.concat([ma, mb], axis=1, join="inner", keys=["a", "b"]).dropna()
    if len(joined) < 3:
        return {"label": label, "n_months": len(joined), "diff": np.nan, "t": np.nan}
    d = joined["a"] - joined["b"]
    n = len(d)
    mu = float(d.mean())
    se = float(d.std(ddof=1)) / np.sqrt(n)
    return {
        "label": label,
        "n_a": int(len(a)),
        "n_b": int(len(b)),
        "n_months": int(n),
        "mean_a": float(ma.reindex(joined.index).mean()),
        "mean_b": float(mb.reindex(joined.index).mean()),
        "diff": mu,
        "t": float(mu / se) if se > 0 else np.nan,
        "ci_lo": float(mu - 1.96 * se) if se > 0 else np.nan,
        "ci_hi": float(mu + 1.96 * se) if se > 0 else np.nan,
    }
