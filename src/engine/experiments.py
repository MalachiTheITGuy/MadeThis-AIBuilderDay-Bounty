"""Experiment science surface (Issue #41, P2-2).

Makes the loop's learning visible as data, not prose:
1. Per-variant Beta posterior credible intervals + pairwise win probabilities.
2. Regret / convergence bucketed by cycle — the visual 'learning happened' proof.

Pure stdlib (no scipy): Beta quantiles via continued-fraction regularized
incomplete beta; win probabilities via random.betavariate Monte Carlo.
"""

from __future__ import annotations

import math
import random
import sqlite3

from src.domain.enums import OutcomeResult

_SUCCESS_RESULTS = {
    OutcomeResult.REPLY,
    OutcomeResult.MEETING,
    OutcomeResult.POSITIVE,
}


# ---------------------------------------------------------------------------
# Beta posterior helpers (Beta(1,1) prior → Beta(1+successes, 1+failures))
# ---------------------------------------------------------------------------

def _log_gamma(x: float) -> float:
    """Lanczos approximation of ln(Γ(x))."""
    _COEF = (
        676.5203681218851, -1259.1392167224028, 771.32342877765313,
        -176.61502916214059, 12.507343278686905, -0.13857109526572012,
        9.9843695780195716e-6, 1.5056327351493116e-7,
    )
    if x < 0.5:
        return math.log(math.pi / math.sin(math.pi * x)) - _log_gamma(1.0 - x)
    x -= 1.0
    a = 0.99999999999980993
    for i in range(8):
        a += _COEF[i] / (x + i + 1.0)
    t = x + 7.5
    return 0.5 * math.log(2.0 * math.pi) + (x + 0.5) * math.log(t) - t + math.log(a)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    MAXIT = 200
    EPS = 3.0e-12
    FPMIN = 1.0e-300

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _ibeta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_factor = (
        _log_gamma(a + b) - _log_gamma(a) - _log_gamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    front = math.exp(ln_factor) / a
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x)
    return 1.0 - front * _betacf(b, a, 1.0 - x)


def beta_quantile(p: float, a: float, b: float) -> float:
    """Quantile (inverse CDF) of Beta(a, b) via bisection on I_x(a, b)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _ibeta(mid, a, b) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def posterior_stats(successes: int, sent: int) -> dict:
    """Beta(1,1)-prior posterior stats for a variant.

    Returns posterior mean, 95% credible interval, and prior/posterior alpha/beta.
    """
    a = successes + 1
    b = (sent - successes) + 1
    mean = a / (a + b)
    return {
        "successes": successes,
        "sent": sent,
        "posterior_mean": round(mean, 4),
        "ci_low": round(beta_quantile(0.025, a, b), 4),
        "ci_high": round(beta_quantile(0.975, a, b), 4),
        "alpha": a,
        "beta": b,
    }


def win_probability(a: float, b: float, other_alphas: list[float], other_betas: list[float], n: int = 2000) -> float:
    """P(variant beats max of others) via Monte Carlo Beta sampling."""
    if not other_alphas:
        return 1.0
    wins = 0
    rng = random.Random(42)
    for _ in range(n):
        x = rng.betavariate(a, b)
        best_other = max(
            rng.betavariate(oa, ob) for oa, ob in zip(other_alphas, other_betas)
        )
        if x > best_other:
            wins += 1
    return round(wins / n, 4)


def _per_variant_counts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Count sent/successful actions per variant from the outcomes history.

    A variant's 'sent' count is the number of actions recorded against it that
    have an outcome; 'successes' are REPLY/MEETING/POSITIVE outcomes.
    """
    rows = conn.execute(
        "SELECT a.variant_id, o.result FROM outcomes o "
        "JOIN actions a ON a.id = o.action_id"
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for r in rows:
        variant = r["variant_id"]
        counts.setdefault(variant, {"sent": 0, "successes": 0})
        counts[variant]["sent"] += 1
        try:
            result = OutcomeResult(r["result"])
        except ValueError:
            continue
        if result in _SUCCESS_RESULTS:
            counts[variant]["successes"] += 1
    return counts


# ---------------------------------------------------------------------------
# Analysis surface
# ---------------------------------------------------------------------------

def analysis(conn: sqlite3.Connection, min_samples: int = 5) -> list[dict]:
    """Per-variant credible intervals + probability of beating the best other.

    Variants with fewer than `min_samples` outcomes are flagged 'paused'
    (too little data to be meaningful) but still reported.
    """
    counts = _per_variant_counts(conn)
    stats = {vid: posterior_stats(v["successes"], v["sent"]) for vid, v in counts.items()}
    if not stats:
        return []

    alphas = {vid: s["alpha"] for vid, s in stats.items()}
    betas = {vid: s["beta"] for vid, s in stats.items()}

    result = []
    for vid, s in stats.items():
        others = [alphas[o] for o in stats if o != vid]
        other_betas = [betas[o] for o in stats if o != vid]
        result.append({
            "variant_id": vid,
            "posterior_mean": s["posterior_mean"],
            "ci_low": s["ci_low"],
            "ci_high": s["ci_high"],
            "sent": s["sent"],
            "successes": s["successes"],
            "win_probability": win_probability(s["alpha"], s["beta"], others, other_betas),
            "paused": s["sent"] < min_samples,
        })
    result.sort(key=lambda r: r["posterior_mean"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# Regret / convergence surface
# ---------------------------------------------------------------------------

def regret_by_cycle(conn: sqlite3.Connection, cycle_size: int = 5) -> list[dict]:
    """Per-cycle regret = (best achievable success rate − achieved rate).

    Buckets the chronological outcome history into cycles of `cycle_size`.
    Best achievable rate for a cycle = the highest posterior mean among
    variants with data at that point; achieved = successes / sent in cycle.
    A declining regret series is the visual 'learning happened' proof.
    """
    rows = conn.execute(
        "SELECT a.variant_id, o.result, o.at FROM outcomes o "
        "JOIN actions a ON a.id = o.action_id "
        "ORDER BY o.at"
    ).fetchall()

    cycles: list[dict] = []
    running_counts: dict[str, dict[str, int]] = {}
    for start in range(0, len(rows), cycle_size):
        bucket = rows[start : start + cycle_size]
        sent = len(bucket)
        successes = 0
        for r in bucket:
            variant = r["variant_id"]
            running_counts.setdefault(variant, {"sent": 0, "successes": 0})
            running_counts[variant]["sent"] += 1
            try:
                result = OutcomeResult(r["result"])
            except ValueError:
                continue
            if result in _SUCCESS_RESULTS:
                running_counts[variant]["successes"] += 1
                successes += 1
        achieved = successes / sent if sent else 0.0
        best_rate = max(
            (
                posterior_stats(c["successes"], c["sent"])["posterior_mean"]
                for c in running_counts.values() if c["sent"] > 0
            ),
            default=0.0,
        )
        cycles.append({
            "cycle": len(cycles) + 1,
            "sent": sent,
            "successes": successes,
            "achieved_rate": round(achieved, 4),
            "best_rate": round(best_rate, 4),
            "regret": round(max(0.0, best_rate - achieved), 4),
        })
    return cycles
