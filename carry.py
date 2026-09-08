"""Carry and roll-down on repo-financed cash Treasuries.

The trade being measured: buy the current par bond at tenor T, finance it in
repo, hold for `horizon`, sell. Everything is quoted in basis points of *yield*,
which is how a desk sizes it - "the 10y gives you 11bp of cushion over 3
months" means yields can back up 11bp before the position stops beating its
financing cost.

Two horizon prices matter, and their difference is the whole P&L:

  P_fwd  the breakeven. Cash-and-carry: the price at which the trade exactly
         repays repo. Earn it and your excess return is zero, by construction.
  P_unch what the bond is actually worth at the horizon if the *spot* curve is
         unchanged - i.e. the same yield-by-maturity function applies to a bond
         that is now `horizon` years shorter.

Converting both to yields on the seasoned (T - horizon) bond gives an exact,
approximation-free split:

    roll-down = y_spot - y_unch     the bond ages into a lower point on an
                                    upward-sloping curve
    carry     = y_fwd - y_spot      coupon income net of repo cost
    total     = y_fwd - y_unch      = carry + roll-down, identically

Positive numbers are always in the holder's favour.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from curve import Curve, cashflow_times, mod_duration, yield_from_price

BENCHMARKS = (2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0)
HORIZON = 0.25  # 3 months
ACT360 = 365 / 360  # repo accrues act/360; horizons here are act/365 year fractions

# Standard curve trades. Spreads are keyed (short leg, long leg) and reported
# as the steepener; flies are (wing, belly, wing) and reported as long-belly.
SPREADS = {"2s10s": (2.0, 10.0), "5s30s": (5.0, 30.0), "2s5s": (2.0, 5.0),
           "10s30s": (10.0, 30.0)}
FLIES = {"2s5s10s": (2.0, 5.0, 10.0), "5s10s30s": (5.0, 10.0, 30.0)}


def forward_price(coupon: float, repo: float, horizon: float,
                  freq: int = 2) -> float:
    """Cash-and-carry forward price per 100 face, full (dirty) basis.

    Buy at par, fund at `repo`, reinvest any coupon received before the horizon
    at the same rate, deliver the bond. Prices are full throughout this module:
    accrued interest at the horizon is identical under both scenarios, so it
    cancels out of every difference below, and carrying it around only invites
    the clean/dirty mismatch that makes roll-down come out backwards.
    """
    dirty = 100 * (1 + repo * horizon * ACT360)
    for t in np.arange(1, int(horizon * freq) + 1) / freq:
        dirty -= 100 * coupon / freq * (1 + repo * (horizon - t) * ACT360)
    return dirty


def implied_repo(c: Curve, horizon: float = HORIZON) -> float:
    """The money-market financing rate the curve itself implies over `horizon`.

    Funded here, cash-and-carry reproduces the curve's own forward prices and
    every tenor's total carry/roll is exactly zero - it is the no-edge point.
    Note it is NOT the coupon: repo pays simple interest on act/360 while a
    bond yield compounds semiannually on act/act, and that basis alone is worth
    a bp or so of "carry" at the front end.

    Actual repo below this rate means the market is funding Treasuries more
    cheaply than the curve assumes, and every tenor carries positively.
    """
    return (1 / float(c.df(horizon)) - 1) / (horizon * ACT360)


def tenor(c: Curve, t: float, repo: float, horizon: float = HORIZON) -> dict:
    """Carry/roll decomposition for one benchmark tenor. All yields decimal."""
    coupon = float(c.par(t))          # par bond: coupon = par yield, price = 100
    seasoned = t - horizon

    px_fwd = forward_price(coupon, repo, horizon)
    px_unch = c.pv(coupon, seasoned)  # spot curve unchanged at the horizon

    y_fwd = yield_from_price(px_fwd, coupon, seasoned)
    y_unch = yield_from_price(px_unch, coupon, seasoned)

    return {
        "tenor": t,
        "yield": coupon,
        "repo": repo,
        "fwd_yield": y_fwd,
        "unch_yield": y_unch,
        "carry_bp": (y_fwd - coupon) * 1e4,
        "roll_bp": (coupon - y_unch) * 1e4,
        "total_bp": (y_fwd - y_unch) * 1e4,
        # Excess return over financing, in bp of price, if the curve does not move.
        "excess_ret_bp": (px_unch - px_fwd) * 100,
        "mod_dur": mod_duration(coupon, t, coupon),
        "dv01": mod_duration(coupon, seasoned, y_unch) * px_unch / 1e4,
    }


def snapshot(par: dict[float, float], repo: float, horizon: float = HORIZON,
             tenors=BENCHMARKS) -> pd.DataFrame:
    """Carry/roll across the benchmark curve for one day."""
    c = Curve(par)
    return pd.DataFrame([tenor(c, t, repo, horizon) for t in tenors]
                        ).set_index("tenor")


def curve_trades(snap: pd.DataFrame) -> pd.Series:
    """Carry + roll on DV01-neutral curve trades, in bp of the spread.

    Sign convention, stated because it is the easiest thing in this file to get
    backwards:

      spreads  the STEEPENER - long the short-maturity leg, short the long
               one, DV01 matched. Its carry is the short leg's total minus the
               long leg's, so a positive number means the steepener is paid to
               wait and the flattener bleeds. Equivalently, it is how far the
               spread can narrow over the horizon before the steepener stops
               beating its financing.

      flies    LONG THE BELLY - two units of the middle tenor against one of
               each wing, DV01 matched. Positive means the belly out-carries
               the wings.

    Both are verified against a first-principles P&L in
    `test_steepener_sign_matches_pnl`.
    """
    tot = snap["total_bp"]
    return pd.Series({**steepener_carry(tot), **fly_carry(tot)})


def steepener_carry(tot):
    """Steepener carry per spread, from a `total_bp` series (one day) or a
    date-by-tenor frame (a history). Defined once so the daily table and the
    time series cannot drift apart on sign."""
    return {k: tot[a] - tot[b] for k, (a, b) in SPREADS.items()}


def fly_carry(tot):
    """Long-belly fly carry, same input shapes as `steepener_carry`."""
    return {k: 2 * tot[m] - tot[a] - tot[b] for k, (a, m, b) in FLIES.items()}


def history(df: pd.DataFrame, cmt_map: dict[str, float], repo_col: str,
            horizon: float = HORIZON, tenors=BENCHMARKS) -> pd.DataFrame:
    """Daily carry/roll history. Returns a (date x tenor) frame per metric,
    concatenated with a `metric` column level."""
    rows = {}
    for date, row in df.iterrows():
        par = {m: row[s] / 100 for s, m in cmt_map.items() if pd.notna(row[s])}
        repo = row[repo_col] / 100
        if pd.isna(repo):
            continue
        rows[date] = snapshot(par, repo, horizon, tenors)
    panel = pd.concat(rows, names=["date", "tenor"])
    return panel.unstack("tenor")


if __name__ == "__main__":
    import fred

    d = fred.load()
    last = d.index[-1]
    snap = snapshot(fred.curve_on(d, last), d.loc[last, "SOFR"] / 100)
    print(f"{last.date()}  repo {d.loc[last, 'SOFR']:.2f}%\n")
    cols = ["yield", "carry_bp", "roll_bp", "total_bp", "excess_ret_bp", "mod_dur"]
    print((snap[cols].assign(**{"yield": snap["yield"] * 100})).round(2).to_string())
    print("\ncurve trades (bp per 3m; spreads = steepener, flies = long belly):")
    print(curve_trades(snap).round(2).to_string())
