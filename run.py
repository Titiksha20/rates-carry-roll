"""Build the carry/roll exhibit pack.

    python run.py                # last 1y of history, cached FRED data
    python run.py --years 2 --refresh

Writes charts and tables to output/.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

import carry
import fred
from curve import Curve

OUT = Path(__file__).parent / "output"
KEY = [2.0, 5.0, 10.0, 30.0]      # tenors carried through the time-series charts

# Palette. Categorical slots are used in fixed order and never cycled; the
# diverging ramp is blue<->red through a neutral grey so zero reads as nothing.
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#7a7975", "#e8e7e4"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
DIVERGING = LinearSegmentedColormap.from_list(
    "bl_rd", ["#0d366b", "#2a78d6", "#9ec5f4", "#f0efec",
              "#f6bdbc", "#e34948", "#8b1a1a"])


def style():
    mpl.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
        "savefig.facecolor": "#fcfcfb", "figure.dpi": 150,
        "font.family": "DejaVu Sans", "font.size": 9,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
        "axes.linewidth": 0.8, "axes.grid": True, "axes.axisbelow": True,
        "grid.color": GRID, "grid.linewidth": 0.7,
        "xtick.color": INK2, "ytick.color": INK2,
        "xtick.major.size": 3, "ytick.major.size": 0,
        "legend.frameon": False, "lines.linewidth": 2, "lines.solid_capstyle": "round",
    })


def frame(ax, title, subtitle="", ylab="", source="Source: FRED (H.15, SOFR); author's calculations."):
    """Exhibit chrome: left-aligned title block, recessive axes, source note."""
    ax.set_title(title, loc="left", fontsize=11.5, fontweight="bold",
                 color=INK, pad=18 if subtitle else 8)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=8.8,
                color=INK2, va="bottom")
    ax.set_ylabel(ylab, fontsize=8.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_visible(False)
    if source:
        ax.figure.text(0.008, -0.02, source, fontsize=7, color=MUTED)


def save(fig, name):
    fig.savefig(OUT / name, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    print(f"  wrote output/{name}")


def label_last(ax, x, y, text, color, dx=6):
    ax.annotate(text, (x, y), xytext=(dx, 0), textcoords="offset points",
                color=color, fontsize=8.5, fontweight="bold", va="center")


# ------------------------------------------------------------------ exhibits

def ex1_curve(c: Curve, date, repo, horizon):
    grid = np.linspace(0.5, 30, 200)
    fwd = np.array([c.forward_par(horizon, m) for m in
                    np.arange(1, 61) / 2])
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.plot(grid, c.par(grid) * 100, color=SERIES[0], label="Par (CMT)")
    ax.plot(grid, c.zero(grid) * 100, color=SERIES[1], label="Zero (bootstrapped)")
    ax.plot(np.arange(1, 61) / 2, np.array(fwd) * 100, color=SERIES[2],
            ls=(0, (5, 2)), label=f"Par, {int(horizon*12)}m forward")
    ax.scatter(list(c.par_input), [v * 100 for v in c.par_input.values()],
               s=22, color=SERIES[0], zorder=5, edgecolor="#fcfcfb", linewidth=1.2)
    ax.axhline(repo * 100, color=MUTED, lw=1, ls=(0, (1, 2)))
    ax.text(0.4, repo * 100, f"SOFR {repo*100:.2f}%", color=MUTED, fontsize=8,
            va="bottom", ha="left")
    frame(ax, "Exhibit 1 · The Treasury curve, three ways",
          f"Par CMT quotes, the zero curve stripped from them, and where the curve "
          f"must sit in {int(horizon*12)}m to break even · {date:%d %b %Y}", "%")
    ax.set_xlabel("Maturity (years)", fontsize=8.8)
    ax.set_xlim(0, 31)
    ax.legend(loc="center right", fontsize=8.5, bbox_to_anchor=(1.0, 0.36))
    save(fig, "ex1_curve.png")


def ex2_carry_roll(snap: pd.DataFrame, date, horizon):
    x = np.arange(len(snap))
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    w = 0.34
    ax.bar(x - w / 2, snap["carry_bp"], w, color=SERIES[0], label="Carry",
           edgecolor="#fcfcfb", linewidth=1)
    ax.bar(x + w / 2, snap["roll_bp"], w, color=SERIES[1], label="Roll-down",
           edgecolor="#fcfcfb", linewidth=1)
    ax.plot(x, snap["total_bp"], ls="none", marker="D", ms=6.5,
            color=INK, label="Total", zorder=6)
    for xi, v in zip(x, snap["total_bp"]):
        ax.annotate(f"{v:.1f}", (xi, v), xytext=(0, 9), textcoords="offset points",
                    ha="center", fontsize=8.5, fontweight="bold", color=INK)
    ax.axhline(0, color=MUTED, lw=0.9)
    ax.set_xticks(x, [f"{int(t)}y" for t in snap.index])
    span = snap[["carry_bp", "roll_bp", "total_bp"]].to_numpy()
    ax.set_ylim(min(0, span.min() * 1.35), span.max() * 1.28)
    frame(ax, f"Exhibit 2 · {int(horizon*12)}-month carry and roll-down, by tenor",
          f"Basis points of yield cushion before a repo-financed long stops paying "
          f"· {date:%d %b %Y}", "bp of yield")
    ax.legend(loc="upper right", fontsize=8.5, ncol=3)
    save(fig, "ex2_carry_roll.png")


def ex3_history(tot: pd.DataFrame, horizon):
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    for i, t in enumerate(KEY):
        ax.plot(tot.index, tot[t], color=SERIES[i], label=f"{int(t)}y")
        label_last(ax, tot.index[-1], tot[t].iloc[-1], f" {int(t)}y", SERIES[i])
    ax.axhline(0, color=MUTED, lw=0.9)
    ax.margins(x=0.02)
    frame(ax, f"Exhibit 3 · Where the carry went",
          f"{int(horizon*12)}m carry + roll-down, rolling daily · the front end went "
          f"from the worst place on the curve to the best", "bp of yield")
    ax.legend(loc="upper left", fontsize=8.5, ncol=4)
    save(fig, "ex3_history.png")


def ex4_heatmap(tot: pd.DataFrame, horizon):
    m = tot.resample("ME").mean().T
    lim = np.abs(m.values).max()
    fig, ax = plt.subplots(figsize=(8.8, 3.8))
    im = ax.imshow(m.values, cmap=DIVERGING, aspect="auto",
                   norm=TwoSlopeNorm(0, -lim, lim))
    ax.set_xticks(range(m.shape[1]), [d.strftime("%b\n%y") for d in m.columns],
                  fontsize=7.6)
    ax.set_yticks(range(m.shape[0]), [f"{int(t)}y" for t in m.index])
    ax.grid(False)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m.values[i, j]
            txt = f"{v:.0f}".removeprefix("-0") or "0"
            ax.text(j, i, txt if txt != "0" else "0", ha="center", va="center", fontsize=7.4,
                    color="#ffffff" if abs(v) > 0.62 * lim else INK)
    fig.colorbar(im, ax=ax, pad=0.015, label="bp").outline.set_visible(False)
    frame(ax, "Exhibit 4 · Carry migrates down the curve",
          f"Monthly average {int(horizon*12)}m carry + roll-down, bp of yield", "")
    for s in ax.spines.values():
        s.set_visible(False)
    save(fig, "ex4_heatmap.png")


def ex5_curve_trades(spreads: pd.DataFrame, levels: pd.DataFrame):
    names = ["2s10s", "5s30s"]
    fig, axes = plt.subplots(2, 1, figsize=(8.4, 5.6), sharex=True,
                             gridspec_kw={"hspace": 0.28})
    for i, n in enumerate(names):
        axes[0].plot(levels.index, levels[n], color=SERIES[i], label=n)
        label_last(axes[0], levels.index[-1], levels[n].iloc[-1], f" {n}", SERIES[i])
        axes[1].plot(spreads.index, spreads[n], color=SERIES[i], label=n)
        label_last(axes[1], spreads.index[-1], spreads[n].iloc[-1], f" {n}", SERIES[i])
    axes[1].axhline(0, color=MUTED, lw=0.9)
    for a in axes:
        a.margins(x=0.02)
    frame(axes[0], "Exhibit 5 · What the curve pays you to wait",
          "Curve level, and three months of carry on the steepener",
          "Spread (bp)", source="")
    frame(axes[1], "", "", "Carry + roll (bp)")
    save(fig, "ex5_curve_trades.png")


def ex6_carry_to_vol(snap: pd.DataFrame, vol: pd.Series, date, horizon):
    ratio = snap["total_bp"] / vol
    x = np.arange(len(ratio))
    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    ax.bar(x, ratio, 0.55, color=[SERIES[0] if v >= 0 else SERIES[1] for v in ratio],
           edgecolor="#fcfcfb", linewidth=1)
    for xi, (v, sd) in enumerate(zip(ratio, vol)):
        ax.annotate(f"{v:.2f}", (xi, v), xytext=(0, 4 if v >= 0 else -12),
                    textcoords="offset points", ha="center", fontsize=8.5,
                    fontweight="bold", color=INK)
        ax.annotate(f"σ {sd:.0f}bp", (xi, 0), xytext=(0, 10),
                    textcoords="offset points", ha="center", fontsize=7.4,
                    color="#ffffff", fontweight="bold")
    ax.axhline(0, color=MUTED, lw=0.9)
    ax.set_xticks(x, [f"{int(t)}y" for t in ratio.index])
    frame(ax, "Exhibit 6 · Carry per unit of risk",
          f"Total carry + roll divided by trailing {int(horizon*12)}m realised yield "
          f"volatility · {date:%d %b %Y}", "carry ÷ σ")
    save(fig, "ex6_carry_to_vol.png")


# ---------------------------------------------------------------------- main

def realised_vol(df: pd.DataFrame, horizon: float, window: int = 63) -> pd.Series:
    """Trailing realised vol of daily yield changes, scaled to the horizon, in bp."""
    chg = df[[f"DGS{int(t)}" for t in carry.BENCHMARKS]].diff() * 100
    ann = chg.tail(window).std() * np.sqrt(252)
    ann.index = list(carry.BENCHMARKS)
    return ann * np.sqrt(horizon)


def main(years: float, refresh: bool, horizon: float):
    style()
    OUT.mkdir(exist_ok=True)
    df = fred.load(refresh=refresh)
    last = df.index[-1]
    hist = df[df.index >= last - pd.DateOffset(years=years)]

    par = fred.curve_on(df, last)
    repo = df.loc[last, "SOFR"] / 100
    c = Curve(par)
    snap = carry.snapshot(par, repo, horizon)
    trades = carry.curve_trades(snap)

    panel = carry.history(hist, fred.CMT, "SOFR", horizon)
    tot = panel["total_bp"]
    spread_carry = pd.DataFrame(carry.steepener_carry(tot))
    levels = pd.DataFrame(
        {n: (hist[f"DGS{int(b)}"] - hist[f"DGS{int(a)}"]) * 100
         for n, (a, b) in carry.SPREADS.items()})
    vol = realised_vol(df, horizon)

    snap.round(6).to_csv(OUT / "carry_roll_latest.csv")
    tot.round(3).to_csv(OUT / "carry_roll_history.csv")
    spread_carry.round(3).to_csv(OUT / "spread_carry_history.csv")
    pd.DataFrame({"zero": c.zero(c.grid), "par": c.par_grid, "df": c.dfs},
                 index=pd.Index(c.grid, name="maturity")
                 ).round(8).to_csv(OUT / "zero_curve_latest.csv")

    ex1_curve(c, last, repo, horizon)
    ex2_carry_roll(snap, last, horizon)
    ex3_history(tot, horizon)
    ex4_heatmap(tot, horizon)
    ex5_curve_trades(spread_carry, levels)
    ex6_carry_to_vol(snap, vol, last, horizon)

    write_summary(last, repo, c, snap, trades, tot, vol, horizon, years)


def write_summary(last, repo, c, snap, trades, tot, vol, horizon, years):
    be = carry.implied_repo(c, horizon)
    best = snap["total_bp"].idxmax()
    ratio = (snap["total_bp"] / vol)
    yr = tot.iloc[0]
    lines = [
        f"# Carry & roll-down — {last:%d %b %Y}", "",
        f"- Financing (SOFR): **{repo*100:.2f}%**. Curve-implied "
        f"{int(horizon*12)}m breakeven repo: **{be*100:.2f}%** "
        f"({'cheap' if repo < be else 'rich'} by {abs(repo-be)*1e4:.0f}bp — "
        f"{'funding below the curve, so every tenor carries positively' if repo < be else 'funding above the curve'}).",
        f"- Richest {int(horizon*12)}m carry + roll: **{int(best)}y at "
        f"{snap.loc[best,'total_bp']:.1f}bp** "
        f"({snap.loc[best,'carry_bp']:.1f} carry, {snap.loc[best,'roll_bp']:.1f} roll).",
        f"- Best carry per unit of risk: **{int(ratio.idxmax())}y at "
        f"{ratio.max():.2f}x** trailing {int(horizon*12)}m yield vol.",
        f"- A year ago the 2y offered **{yr[2.0]:.1f}bp** and the 30y "
        f"**{yr[30.0]:.1f}bp**; today it is **{snap.loc[2.0,'total_bp']:.1f}bp** "
        f"and **{snap.loc[30.0,'total_bp']:.1f}bp**.", "",
        "## Curve trades (bp per horizon)", "",
        "_Spreads are quoted as the DV01-neutral **steepener**; positive means the "
        "steepener is paid to wait. Flies are **long the belly**._", "",
        "| trade | carry + roll |", "| --- | ---: |",
        *[f"| {k} | {v:+.1f} |" for k, v in trades.items()], "",
        "## By tenor", "",
        snap[["yield", "carry_bp", "roll_bp", "total_bp", "excess_ret_bp",
              "mod_dur"]].assign(**{"yield": snap["yield"] * 100})
        .round(2).to_markdown(),
        "", f"_{years:g}y of daily history, {len(tot)} observations. "
        f"Generated by `run.py`._",
    ]
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    print("  wrote output/summary.md\n")
    print("\n".join(lines[:9]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=float, default=1)
    p.add_argument("--horizon", type=float, default=carry.HORIZON,
                   help="holding period in years (default 0.25)")
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    main(a.years, a.refresh, a.horizon)
