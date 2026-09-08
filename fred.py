"""FRED data access for the US Treasury constant-maturity (CMT) curve.

Uses the public fredgraph.csv endpoint, so no API key is required. Everything
is cached to data/ so the rest of the project runs offline and reproducibly.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).parent / "data"
FREDGRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# H.15 constant-maturity Treasury series -> maturity in years.
# 1M-1Y are bond-equivalent yields derived from bills; 2Y+ are par coupon yields.
CMT = {
    "DGS1MO": 1 / 12,
    "DGS3MO": 0.25,
    "DGS6MO": 0.5,
    "DGS1": 1.0,
    "DGS2": 2.0,
    "DGS3": 3.0,
    "DGS5": 5.0,
    "DGS7": 7.0,
    "DGS10": 10.0,
    "DGS20": 20.0,
    "DGS30": 30.0,
}

# Overnight SOFR, the financing-rate proxy for a repo-funded cash Treasury position.
FINANCING = "SOFR"


def _download(series: list[str], start: str) -> pd.DataFrame:
    r = requests.get(
        FREDGRAPH, params={"id": ",".join(series), "cosd": start}, timeout=60
    )
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), parse_dates=["observation_date"])
    return df.set_index("observation_date").apply(pd.to_numeric, errors="coerce")


def load(start: str = "2015-01-01", refresh: bool = False) -> pd.DataFrame:
    """Daily CMT yields + SOFR, in percent. Columns are the FRED series ids.

    Rows are business days on which at least the 2y-30y curve printed; H.15 has
    gaps on bond-market holidays and occasional single-series misses, which are
    forward-filled for at most 5 days before the row is dropped.
    """
    cache = DATA / "fred_cmt.csv"
    if refresh or not cache.exists():
        DATA.mkdir(exist_ok=True)
        _download(list(CMT) + [FINANCING], start).to_csv(cache)

    df = pd.read_csv(cache, parse_dates=["observation_date"], index_col=0)
    core = ["DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS30"]
    df = df[df[core].notna().all(axis=1)]
    return df.ffill(limit=5).dropna(subset=list(CMT))


def curve_on(df: pd.DataFrame, date) -> dict[float, float]:
    """One day's CMT curve as {maturity_years: yield_decimal}."""
    row = df.loc[date]
    return {CMT[s]: row[s] / 100.0 for s in CMT if pd.notna(row[s])}


if __name__ == "__main__":
    d = load(refresh=True)
    print(f"{len(d)} rows, {d.index[0].date()} -> {d.index[-1].date()}")
    print(d.tail(3).to_string())
