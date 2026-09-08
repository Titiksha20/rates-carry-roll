"""Self-checks for the curve bootstrap and the carry/roll decomposition.

Plain asserts, no framework:  python test_rates.py
"""

import numpy as np

import carry
from curve import Curve, mod_duration, price, yield_from_price

FLAT = {t: 0.05 for t in (0.5, 1, 2, 3, 5, 7, 10, 20, 30)}
UP = {0.5: 0.0390, 1: 0.0405, 2: 0.0430, 3: 0.0445, 5: 0.0460,
      7: 0.0475, 10: 0.0490, 20: 0.0525, 30: 0.0530}


def test_flat_curve_is_flat():
    """A flat 5% par curve must strip to a flat 5% zero curve."""
    c = Curve(FLAT)
    z = c.zero(np.array([0.5, 1, 5, 10, 30]))
    assert np.allclose(z, 0.05, atol=1e-12), z
    assert np.allclose(c.df(np.array([0.5, 10.0])),
                       (1 + 0.05 / 2) ** (-2 * np.array([0.5, 10.0])), atol=1e-12)


def test_bootstrap_reprices_par_bonds():
    """Every input par yield must reprice its own bond to exactly 100."""
    for par in (FLAT, UP):
        c = Curve(par)
        for t in par:
            assert abs(c.pv(par[t], t) - 100) < 1e-9, (t, c.pv(par[t], t))


def test_zeros_above_par_when_curve_slopes_up():
    c = Curve(UP)
    for t in (2, 5, 10, 30):
        assert c.zero(t) > c.par(t), t


def test_price_yield_roundtrip():
    for mat in (1.75, 4.75, 9.75, 29.5):
        for y in (0.001, 0.03, 0.09):
            px = price(0.045, mat, y)
            assert abs(yield_from_price(px, 0.045, mat) - y) < 1e-10


def test_mod_duration_matches_a_bump():
    """Analytic duration must match a 1bp central difference. The residual is
    the difference quotient's own O(h^2) truncation, not a pricing error."""
    c, m, y = 0.045, 9.75, 0.047
    bumped = (price(c, m, y - 1e-4) - price(c, m, y + 1e-4)) / (2e-4)
    assert abs(bumped / price(c, m, y) - mod_duration(c, m, y)) < 1e-5


def test_forward_price_is_arbitrage_free():
    """Fund at the curve's own 3m rate and cash-and-carry must reproduce the
    curve-implied forward price exactly."""
    c = Curve(UP)
    h = carry.HORIZON
    implied_repo = (1 / float(c.df(h)) - 1) / (h * carry.ACT360)
    for t in (2.0, 10.0, 30.0):
        cpn = float(c.par(t))
        cash = carry.forward_price(cpn, implied_repo, h)
        curve_implied = c.pv(cpn, t - h, shift=h)
        assert abs(cash - curve_implied) < 1e-9, (t, cash, curve_implied)


def test_carry_plus_roll_is_the_total():
    """The decomposition is exact, not an approximation - it must sum."""
    snap = carry.snapshot(UP, repo=0.038)
    resid = (snap["carry_bp"] + snap["roll_bp"] - snap["total_bp"]).abs().max()
    assert resid < 1e-9, resid


def test_flat_curve_has_no_roll():
    """No slope, nothing to roll down - whatever the funding rate is."""
    for r in (0.02, 0.05, 0.08):
        assert carry.snapshot(FLAT, repo=r)["roll_bp"].abs().max() < 1e-6


def test_breakeven_repo_zeroes_a_flat_curve():
    """On a flat curve the two horizon scenarios coincide, so funding at the
    curve's own implied rate must leave exactly nothing on the table."""
    c = Curve(FLAT)
    snap = carry.snapshot(FLAT, repo=carry.implied_repo(c))
    assert snap["total_bp"].abs().max() < 1e-6, snap["total_bp"]


def test_sloped_curve_pays_even_at_breakeven_funding():
    """The point of the whole exercise. On an upward-sloping curve, funding at
    the curve-implied repo does NOT zero the total: "forwards are realised" and
    "the spot curve doesn't move" are different scenarios, and the gap between
    them is exactly what carry and roll measure. A long that funds at the
    curve's own rate still earns if the curve simply sits still."""
    c = Curve(UP)
    snap = carry.snapshot(UP, repo=carry.implied_repo(c))
    assert (snap["total_bp"] > 0).all(), snap["total_bp"]
    # Same statement in price space: the unchanged-curve price beats the forward.
    assert (snap["excess_ret_bp"] > 0).all()


def test_funding_at_the_coupon_is_not_free():
    """The classic trap: a flat 5% curve funded at 5% still bleeds. Repo pays
    simple interest act/360; the bond compounds semiannually act/act. Both
    bases push the same way, and the drag is largest where duration is least."""
    snap = carry.snapshot(FLAT, repo=0.05)
    assert (snap["total_bp"] < 0).all(), snap["total_bp"]
    assert snap["total_bp"].abs().max() < 2.0, snap["total_bp"]
    assert snap.loc[2, "total_bp"] < snap.loc[30, "total_bp"]
    # The whole gap is the funding basis: it closes at the breakeven repo.
    assert carry.implied_repo(Curve(FLAT)) < 0.05


def test_signs_are_intuitive():
    """Upward-sloping curve, repo below the whole curve: carry and roll both
    pay. Invert the funding and carry must flip."""
    cheap = carry.snapshot(UP, repo=0.030)
    assert (cheap["carry_bp"] > 0).all(), cheap["carry_bp"]
    assert (cheap["roll_bp"] > 0).all(), cheap["roll_bp"]
    assert (cheap["total_bp"] > 0).all()
    dear = carry.snapshot(UP, repo=0.060)
    assert (dear["carry_bp"] < 0).all(), dear["carry_bp"]
    # Roll-down is a property of the curve, not of funding.
    assert np.allclose(cheap["roll_bp"], dear["roll_bp"], atol=1e-9)


def test_excess_return_ties_to_the_yield_number():
    """bp of yield x DV01 must reproduce bp of price. They agree only to
    first order - DV01 is a local slope - so the gap is convexity, and it has
    to stay small relative to the number itself."""
    snap = carry.snapshot(UP, repo=0.035)
    implied = snap["total_bp"] * snap["dv01"] * 100
    rel = ((implied - snap["excess_ret_bp"]) / snap["excess_ret_bp"]).abs()
    assert (rel < 0.01).all(), rel


def test_spread_carry_is_the_difference_of_legs():
    snap = carry.snapshot(UP, repo=0.035)
    tr = carry.curve_trades(snap)
    assert abs(tr["2s10s"] - (snap.loc[2, "total_bp"]
                              - snap.loc[10, "total_bp"])) < 1e-12
    # Upward-sloping curve, repo below the front end: the 2y out-carries the
    # 10y, so the steepener is the leg that gets paid to wait.
    assert tr["2s10s"] > 0


def test_steepener_sign_matches_pnl():
    """The sign convention in `curve_trades`, checked the long way round.

    Build the DV01-neutral steepener explicitly, hold it for the horizon with
    the curve unchanged, and total the excess return of both legs in price
    terms. Its sign must agree with the reported spread carry.

    Note what this does and does not establish. The portfolio is constructed
    here, not taken from the module, and the check crosses price space
    (`excess_ret_bp`, `dv01`) against yield space (`total_bp`) - two different
    calculations inside `tenor()`. It is not an independent reimplementation of
    the pricing, so it would not catch an error common to both. It exists
    because the reported sign is the easiest thing here to state backwards.
    """
    for repo in (0.030, 0.035, 0.055):
        snap = carry.snapshot(UP, repo=repo)
        reported = carry.curve_trades(snap)["2s10s"]
        short_leg, long_leg = snap.loc[2], snap.loc[10]
        # Scale the 2y up to match the 10y's DV01, long 2y / short 10y.
        units = long_leg["dv01"] / short_leg["dv01"]
        pnl = units * short_leg["excess_ret_bp"] - long_leg["excess_ret_bp"]
        assert np.sign(pnl) == np.sign(reported), (repo, pnl, reported)


def test_fly_is_long_the_belly():
    """Fly sign, checked against a constructed P&L rather than a restatement.

    An earlier version asserted sign(2m - a - b) against sign(m - (a+b)/2).
    Those differ by a factor of two, so it could not fail whatever the code
    did. This builds the trade instead: buy 100 face of the belly, sell each
    wing in the amount that splits the belly's DV01 evenly between them, hold
    the horizon with the curve unchanged, total the excess returns in price
    space.
    """
    for repo in (0.030, 0.035, 0.055):
        snap = carry.snapshot(UP, repo=repo)
        reported = carry.curve_trades(snap)["2s5s10s"]
        wing_lo, belly, wing_hi = snap.loc[2], snap.loc[5], snap.loc[10]
        u_lo = 0.5 * belly["dv01"] / wing_lo["dv01"]
        u_hi = 0.5 * belly["dv01"] / wing_hi["dv01"]
        pnl = (belly["excess_ret_bp"]
               - u_lo * wing_lo["excess_ret_bp"]
               - u_hi * wing_hi["excess_ret_bp"])
        assert np.sign(pnl) == np.sign(reported), (repo, pnl, reported)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")
