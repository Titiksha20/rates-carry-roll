"""Par -> zero bootstrap and bond math for the US Treasury curve.

Convention throughout: rates are decimals (0.0478 = 4.78%), maturities are in
years, and yields are semiannual bond-equivalent, matching H.15 CMT quotes.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq

FREQ = 2  # semiannual coupons
MAX_T = 30.0


# ---------------------------------------------------------------- bond math

def cashflow_times(maturity: float, freq: int = FREQ) -> np.ndarray:
    """Times to each remaining cashflow, counted back from maturity.

    A 4.75y bond pays at 0.25, 0.75, ... 4.75 - the stub is at the front, which
    is what a seasoned bond looks like part-way through a coupon period.
    """
    n = int(np.ceil(maturity * freq - 1e-9))
    return maturity - np.arange(n - 1, -1, -1) / freq


def price(coupon: float, maturity: float, ytm: float, freq: int = FREQ) -> float:
    """Full (dirty) price per 100 face from yield: the PV of every remaining
    cashflow, discounted semiannually. For a bond part-way through a coupon
    period this includes accrued interest. Everything in this project compares
    full prices to full prices, so accrued cancels out of every difference.
    """
    t = cashflow_times(maturity, freq)
    cf = np.full(t.size, 100 * coupon / freq)
    cf[-1] += 100
    return float(np.sum(cf * (1 + ytm / freq) ** (-freq * t)))


def yield_from_price(px: float, coupon: float, maturity: float,
                     freq: int = FREQ) -> float:
    """Invert `price`. Bracketed at -50%/+100%, well outside any real quote."""
    return brentq(lambda y: price(coupon, maturity, y, freq) - px,
                  -0.5, 1.0, xtol=1e-12)


def mod_duration(coupon: float, maturity: float, ytm: float,
                 freq: int = FREQ) -> float:
    """Modified duration in years."""
    t = cashflow_times(maturity, freq)
    cf = np.full(t.size, 100 * coupon / freq)
    cf[-1] += 100
    pv = cf * (1 + ytm / freq) ** (-freq * t)
    return float(np.sum(t * pv) / np.sum(pv) / (1 + ytm / freq))


# ------------------------------------------------------------------- curve

class Curve:
    """A zero curve bootstrapped from par (CMT) yields.

    The CMT quotes are par yields on a coarse grid (0.5, 1, 2, 3, 5, 7, 10, 20,
    30y). They are interpolated onto a semiannual grid with a shape-preserving
    PCHIP spline - monotone between knots, so it will not manufacture the
    humps a natural cubic spline invents on a steep curve - and then stripped
    one coupon date at a time:

        DF(0.5) = 1 / (1 + c_1/2)
        DF(t_n) = [1 - (c_n/2) * sum_{i<n} DF(t_i)] / (1 + c_n/2)

    Off-grid discount factors are log-linear in time (equivalently, piecewise
    constant instantaneous forwards), anchored at DF(0) = 1.
    """

    def __init__(self, par: dict[float, float], max_t: float = MAX_T,
                 freq: int = FREQ):
        pts = sorted((t, y) for t, y in par.items() if t >= 1 / freq)
        if not pts:
            raise ValueError("need at least one par point at or beyond 6m")
        self.par_input = dict(pts)
        self.freq = freq
        self._par = PchipInterpolator(*map(np.array, zip(*pts)), extrapolate=False)

        self.grid = np.arange(1, int(max_t * freq) + 1) / freq
        self.par_grid = self._par_at(self.grid)

        df, run = np.empty_like(self.grid), 0.0
        for i, c in enumerate(self.par_grid):
            df[i] = (1 - c / freq * run) / (1 + c / freq)
            run += df[i]
        self.dfs = df

    def _par_at(self, t):
        """Par yields on the interpolation grid; flat beyond the knots."""
        lo, hi = min(self.par_input), max(self.par_input)
        return self._par(np.clip(t, lo, hi))

    def df(self, t):
        """Discount factor(s), log-linear in t between bootstrapped nodes.

        Clamped past the last node; nothing here prices beyond 30y, so that
        edge never binds.
        """
        knots = np.concatenate(([0.0], self.grid))
        logdf = np.concatenate(([0.0], np.log(self.dfs)))
        return np.exp(np.interp(np.asarray(t, dtype=float), knots, logdf))

    def zero(self, t):
        """Semiannual bond-equivalent zero rate(s)."""
        t = np.asarray(t, dtype=float)
        return self.freq * (self.df(t) ** (-1 / (self.freq * t)) - 1)

    def par(self, t):
        """Par (CMT-equivalent) yield at any maturity, from the same spline."""
        return self._par_at(np.asarray(t, dtype=float))

    def forward_zero(self, t1: float, t2: float) -> float:
        """Zero rate between two future dates, semiannual basis."""
        ratio = self.df(t1) / self.df(t2)
        return float(self.freq * (ratio ** (1 / (self.freq * (t2 - t1))) - 1))

    def par_from_dfs(self, dfs) -> float:
        """Par coupon implied by discount factors on a full coupon grid."""
        return float(self.freq * (1 - dfs[-1]) / np.sum(dfs))

    def forward_par(self, horizon: float, maturity: float) -> float:
        """Par yield `horizon` years forward, for a `maturity`-year bond."""
        t = np.arange(1, int(round(maturity * self.freq)) + 1) / self.freq
        dfs = self.df(horizon + t) / self.df(horizon)
        return self.par_from_dfs(dfs)

    def pv(self, coupon: float, maturity: float, shift: float = 0.0) -> float:
        """Present value per 100 face off the zero curve, `shift` years forward
        along the curve (shift=0 prices today; shift>0 prices the same
        cashflow pattern as if today's curve were unchanged at that horizon).
        """
        t = cashflow_times(maturity, self.freq)
        cf = np.full(t.size, 100 * coupon / self.freq)
        cf[-1] += 100
        d = self.df(t + shift) / self.df(shift) if shift else self.df(t)
        return float(np.sum(cf * d))
