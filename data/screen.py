"""
The evidence-backed dip screen — live.

This is the rule set that survived the studies, and only that rule set. Every
threshold here traces to a measured result; nothing is here because it seemed
sensible. The provenance table:

  Z(20) < -1.2 crossing        beats 200/200 random draws at 5/20/60 bars,
                               worth +0.3 to +0.4pp per trade
                               [OVERREACTION_STUDY.md §2]
  depth beyond -1.2            IRRELEVANT -- -1.2, -0.8 and -0.5 are
                               interchangeable, so a deeper dip is not a
                               better dip [STRATEGY_REVIEW.md §5.4]
  no earnings within 20 days   away-from-earnings dips beat post-earnings dips
                               by +0.80pp at 20d, t=2.35, stable in both halves
                               [OVERREACTION_STUDY.md §4]
  market-wide, not lonely      dips where the market dragged the name down beat
                               name-specific dips at every horizon; the "lonely
                               faller" was the worst cohort measured
                               [OVERREACTION_STUDY.md §5]
  edge expires by 120 bars     the signal contributes nothing past ~120 bars;
                               what you hold after that is beta
                               [OVERREACTION_STUDY.md §2]

Rules deliberately NOT implemented, because they were tested and failed:

  volume as a news proxy       t < 1 at every horizon, sign flips across halves
  200-SMA regime gate          cut CAGR by two thirds [§5.9]
  post-earnings size-up        levers into the worst cohort measured [§4, §6]
  stacking every filter        the triple per-event screen lost significance
                               entirely [OVERREACTION_STUDY.md §7]
  fixed-bar time exit          worse than the trail at every setting
                               [OPTIMISATION_STUDY.md §2]
  model-predicted sizing       collapses into a volatility tilt
                               [OPTIMISATION_STUDY.md §3]

The screen's job is to decide WHERE new money goes. It never generates a sell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

BENCHMARK = "SPY"
TRADING_DAYS = 252

# ─────────────────────────────────────────────────────────────
# Universe
# ─────────────────────────────────────────────────────────────
# 124 liquid US names, $20B+, across tech / financials / healthcare /
# consumer / industrials / energy. The breadth matters more than the names:
# PORTFOLIO_STUDY.md §5 measures 30 tech names as only 4.6 independent bets,
# while 50 mixed names is 8.5. Diversification has to happen at the level of
# bets, not tickers, which is why this list is deliberately not all tech.
UNIVERSE_V2 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "ADI",
    "NXPI", "MRVL", "ON", "SWKS", "TER",
    "NOW", "PANW", "CRWD", "DDOG", "NET", "SNOW", "MDB", "ZS", "TEAM", "WDAY",
    "SHOP", "UBER", "ABNB", "PYPL", "INTU", "ADSK", "CDNS", "SNPS",
    "FTNT", "OKTA", "TWLO", "DOCU", "ZM", "ROKU", "PINS", "SNAP", "SPOT", "EBAY",
    "V", "MA", "AXP", "JPM", "BAC", "GS", "MS", "SCHW", "BLK", "SPGI",
    "COIN", "HOOD",
    "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "DHR", "ISRG", "VRTX",
    "REGN", "AMGN", "GILD", "MRNA", "BIIB", "CVS", "ZTS", "SYK", "BSX", "MDT",
    "WMT", "COST", "HD", "LOW", "TGT", "NKE", "SBUX", "MCD", "PG", "KO",
    "PEP", "DIS", "NFLX", "CMG", "LULU", "DG", "ULTA", "YUM", "MAR",
    "CAT", "DE", "BA", "HON", "GE", "UPS", "FDX", "LMT", "RTX", "UNP",
    "XOM", "CVX", "COP", "SLB", "OXY", "NEE", "DUK", "LIN", "APD", "SHW",
]

SECTORS = {
    **{t: "Tech" for t in [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
        "ADBE", "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "ADI",
        "NXPI", "MRVL", "ON", "SWKS", "TER", "NOW", "PANW", "CRWD", "DDOG", "NET",
        "SNOW", "MDB", "ZS", "TEAM", "WDAY", "SHOP", "UBER", "ABNB", "PYPL", "INTU",
        "ADSK", "CDNS", "SNPS", "FTNT", "OKTA", "TWLO", "DOCU", "ZM", "ROKU", "PINS",
        "SNAP", "SPOT", "EBAY", "NFLX"]},
    **{t: "Financials" for t in [
        "V", "MA", "AXP", "JPM", "BAC", "GS", "MS", "SCHW", "BLK", "SPGI",
        "COIN", "HOOD"]},
    **{t: "Healthcare" for t in [
        "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "DHR", "ISRG", "VRTX",
        "REGN", "AMGN", "GILD", "MRNA", "BIIB", "CVS", "ZTS", "SYK", "BSX", "MDT"]},
    **{t: "Consumer" for t in [
        "WMT", "COST", "HD", "LOW", "TGT", "NKE", "SBUX", "MCD", "PG", "KO",
        "PEP", "DIS", "CMG", "LULU", "DG", "ULTA", "YUM", "MAR"]},
    **{t: "Industrials" for t in [
        "CAT", "DE", "BA", "HON", "GE", "UPS", "FDX", "LMT", "RTX", "UNP"]},
    **{t: "Energy / Materials" for t in [
        "XOM", "CVX", "COP", "SLB", "OXY", "NEE", "DUK", "LIN", "APD", "SHW"]},
}


# ─────────────────────────────────────────────────────────────
# Screen configuration
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ScreenSpec:
    key: str
    name: str
    tagline: str
    evidence: str
    z_entry: float = -1.2
    require_no_earnings: bool = False
    earnings_window: int = 20
    require_market_wide: bool = False
    require_not_lonely: bool = False
    # Thresholds fitted on the 17,235-event panel (2015-2026). idio_hi is the
    # 67th percentile of idio_z -- above it, the decline was mostly the market.
    # breadth_lo is the 33rd percentile -- below it, the name is falling alone.
    idio_hi: float = -1.09
    breadth_lo: float = 0.18


EVIDENCE = "evidence"
PER_EVENT = "per_event"
EARNINGS_ONLY = "earnings_only"
RAW = "raw"

SCREENS: dict[str, ScreenSpec] = {
    EVIDENCE: ScreenSpec(
        key=EVIDENCE,
        name="Evidence screen",
        tagline="No earnings · market-wide · not a lonely faller",
        evidence=(
            "Best **deployment** rule tested: beat scheduled investing in all "
            "three windows, mean **+8.0%** on terminal value. "
            "Caveat: those windows are nested, so treat it as roughly one "
            "independent observation, not three."
        ),
        require_no_earnings=True,
        require_market_wide=True,
        require_not_lonely=True,
    ),
    PER_EVENT: ScreenSpec(
        key=PER_EVENT,
        name="Best per-event screen",
        tagline="No earnings · not a lonely faller",
        evidence=(
            "Highest forward excess of any screen: **+1.94pp at 20 days, "
            "t = 5.40**, on 46% of events — and **positive in both halves** "
            "of the sample (+1.36 / +0.84 vs baseline)."
        ),
        require_no_earnings=True,
        require_not_lonely=True,
    ),
    EARNINGS_ONLY: ScreenSpec(
        key=EARNINGS_ONLY,
        name="Earnings filter only",
        tagline="No earnings within 20 days",
        evidence=(
            "The single most robust filter: **+0.80pp at 20 days, t = 2.35**, "
            "stable across both halves. Keeps 68% of events."
        ),
        require_no_earnings=True,
    ),
    RAW: ScreenSpec(
        key=RAW,
        name="Unfiltered dip",
        tagline="Z < −1.2 only — the old Method A/B entry",
        evidence=(
            "Real but small: beats 200/200 random draws, worth +0.34pp at 20 "
            "days. **As a deployment rule on this many names it LOST to "
            "scheduled investing** — something is always dipping, so it "
            "degenerates into DCA with worse selection."
        ),
    ),
}


# ─────────────────────────────────────────────────────────────
# Indicators
# ─────────────────────────────────────────────────────────────
def add_screen_indicators(
    df: pd.DataFrame,
    spy: pd.DataFrame,
    sma_window: int = 20,
    atr_window: int = 14,
    beta_window: int = 120,
) -> pd.DataFrame:
    """
    Indicators for the screen. Identical maths to studies/overreaction_lib.py
    so the live app and the backtest cannot silently diverge.
    """
    d = df.copy()
    c = d["Close"]

    d["ret"] = c.pct_change()
    d["sma"] = c.rolling(sma_window).mean()
    d["sd"] = c.rolling(sma_window).std()
    d["z"] = (c - d["sma"]) / d["sd"]
    # The price at which Z would equal the entry threshold -- the actionable
    # number, because it is a limit price you can actually place.
    d["trigger_z"] = d["sma"]  # filled per-threshold by trigger_price()

    pc = c.shift(1)
    tr = pd.concat(
        [d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()],
        axis=1,
    ).max(axis=1)
    d["atr"] = tr.rolling(atr_window).mean()
    d["rvol20"] = d["ret"].rolling(20).std() * np.sqrt(TRADING_DAYS) * 100

    m = spy["Close"].pct_change().reindex(d.index)
    cov = d["ret"].rolling(beta_window).cov(m)
    var = m.rolling(beta_window).var()
    beta = (cov / var).clip(-3, 3)
    d["beta"] = beta
    resid = d["ret"] - beta * m
    ridx = resid.fillna(0.0).cumsum()
    d["idio_z"] = (ridx - ridx.rolling(sma_window).mean()) / ridx.rolling(sma_window).std()

    return d


def trigger_price(row: pd.Series, z_entry: float) -> float:
    """SMA + z_entry * sd — the price at which Z hits the threshold."""
    sma, sd = row.get("sma"), row.get("sd")
    if pd.isna(sma) or pd.isna(sd):
        return float("nan")
    return float(sma + z_entry * sd)


def days_since_earnings(index: pd.DatetimeIndex, earnings_dates: list) -> float:
    """
    Trading bars since the most recent earnings report at or before the last
    bar. Returns a large number when no report is known, so an unknown name is
    treated as "not near earnings" rather than silently excluded.
    """
    if not earnings_dates or len(index) == 0:
        return 999.0
    last = index[-1]
    past = [pd.Timestamp(e).normalize() for e in earnings_dates
            if pd.notna(e) and pd.Timestamp(e).normalize() <= last]
    if not past:
        return 999.0
    most_recent = max(past)
    return float(int((index > most_recent).sum()))


def days_to_earnings(index: pd.DatetimeIndex, earnings_dates: list) -> Optional[float]:
    """Calendar days until the next known report, or None."""
    if not earnings_dates or len(index) == 0:
        return None
    last = index[-1]
    future = [pd.Timestamp(e).normalize() for e in earnings_dates
              if pd.notna(e) and pd.Timestamp(e).normalize() > last]
    if not future:
        return None
    return float((min(future) - last).days)


# ─────────────────────────────────────────────────────────────
# The screen
# ─────────────────────────────────────────────────────────────
@dataclass
class ScreenResult:
    rows: list[dict] = field(default_factory=list)
    breadth: float = float("nan")
    n_dipping: int = 0
    n_scanned: int = 0
    asof: Optional[pd.Timestamp] = None


def run_screen(
    frames: dict[str, pd.DataFrame],
    earnings: dict[str, list],
    spec: ScreenSpec,
) -> ScreenResult:
    """
    Evaluate every name against the screen and return one row each.

    Breadth is computed across the whole scanned universe on the latest common
    bar, so it means the same thing it meant in the study: what fraction of
    names are simultaneously below the Z threshold.
    """
    enriched: dict[str, pd.DataFrame] = {}
    spy = frames.get(BENCHMARK)
    if spy is None or spy.empty:
        return ScreenResult()

    for t, df in frames.items():
        if t == BENCHMARK or df is None or df.empty or len(df) < 130:
            continue
        enriched[t] = add_screen_indicators(df, spy)

    if not enriched:
        return ScreenResult()

    z_now = {t: float(d["z"].iloc[-1]) for t, d in enriched.items()
             if pd.notna(d["z"].iloc[-1])}
    n_scanned = len(z_now)
    n_dipping = sum(1 for v in z_now.values() if v < spec.z_entry)
    breadth = n_dipping / n_scanned if n_scanned else float("nan")
    not_lonely = bool(breadth > spec.breadth_lo) if n_scanned else False

    asof = max(d.index[-1] for d in enriched.values())

    rows = []
    for t, d in enriched.items():
        last = d.iloc[-1]
        z = float(last["z"]) if pd.notna(last["z"]) else float("nan")
        idio = float(last["idio_z"]) if pd.notna(last["idio_z"]) else float("nan")
        dse = days_since_earnings(d.index, earnings.get(t, []))
        dte = days_to_earnings(d.index, earnings.get(t, []))
        close = float(last["Close"])
        trig = trigger_price(last, spec.z_entry)

        # each gate, evaluated separately so the UI can show WHY a name failed
        g_dip = bool(pd.notna(z) and z < spec.z_entry)
        g_earn = (not spec.require_no_earnings) or (dse > spec.earnings_window)
        g_mkt = (not spec.require_market_wide) or (pd.notna(idio) and idio > spec.idio_hi)
        g_lonely = (not spec.require_not_lonely) or not_lonely

        rows.append({
            "ticker": t,
            "sector": SECTORS.get(t, "Other"),
            "close": close,
            "z": z,
            "idio_z": idio,
            "trigger": trig,
            "dist_pct": (trig / close - 1.0) * 100 if close else float("nan"),
            "atr": float(last["atr"]) if pd.notna(last["atr"]) else float("nan"),
            "rvol20": float(last["rvol20"]) if pd.notna(last["rvol20"]) else float("nan"),
            "beta": float(last["beta"]) if pd.notna(last["beta"]) else float("nan"),
            "days_since_earnings": dse,
            "days_to_earnings": dte,
            "gate_dip": g_dip,
            "gate_no_earnings": g_earn,
            "gate_market_wide": g_mkt,
            "gate_not_lonely": g_lonely,
            "qualifies": bool(g_dip and g_earn and g_mkt and g_lonely),
            "last_bar": d.index[-1],
        })

    rows.sort(key=lambda r: (not r["qualifies"], r["z"] if pd.notna(r["z"]) else 99))
    return ScreenResult(rows=rows, breadth=breadth, n_dipping=n_dipping,
                        n_scanned=n_scanned, asof=asof)


def failed_gates(row: dict, spec: ScreenSpec) -> list[str]:
    """Human-readable reasons a dipping name did not qualify."""
    out = []
    if not row["gate_dip"]:
        out.append(f"Z {row['z']:.2f} is not below {spec.z_entry}")
    if not row["gate_no_earnings"]:
        out.append(f"reported earnings {row['days_since_earnings']:.0f} bars ago")
    if not row["gate_market_wide"]:
        out.append("decline is name-specific, not market-driven")
    if not row["gate_not_lonely"]:
        out.append("too few other names are falling — lonely faller")
    return out


# ─────────────────────────────────────────────────────────────
# Concentration
# ─────────────────────────────────────────────────────────────
def effective_bets(frames: dict[str, pd.DataFrame], tickers: list[str],
                   lookback: int = 504) -> dict:
    """
    How many INDEPENDENT bets a set of names actually represents.

    Participation ratio of the correlation matrix eigenvalue spectrum,
    (sum L)^2 / sum L^2. Equals n when every name is independent and 1 when
    they are all the same bet. PORTFOLIO_STUDY.md §5 measures 30 tech names at
    4.65 and the original META/NVDA/NET trio at 2.10 -- which is why no
    position-sizing rule ever moved the needle on that universe.
    """
    names = [t for t in tickers if t in frames and frames[t] is not None
             and not frames[t].empty]
    if len(names) < 2:
        return {"n_names": len(names), "effective_bets": float(len(names)),
                "avg_corr": float("nan"), "pc1_pct": float("nan")}

    rets = pd.DataFrame({t: frames[t]["Close"].pct_change() for t in names}).tail(lookback)
    rets = rets.dropna(axis=1, thresh=int(len(rets) * 0.8)).dropna()
    if rets.shape[1] < 2 or len(rets) < 30:
        return {"n_names": len(names), "effective_bets": float("nan"),
                "avg_corr": float("nan"), "pc1_pct": float("nan")}

    n = rets.shape[1]
    corr = rets.corr().values
    off = corr[~np.eye(n, dtype=bool)]
    lam = np.clip(np.linalg.eigvalsh(corr), 0, None)
    return {
        "n_names": n,
        "effective_bets": float(lam.sum() ** 2 / (lam ** 2).sum()),
        "avg_corr": float(off.mean()),
        "pc1_pct": float(lam.max() / lam.sum() * 100),
    }
