"""Calibration maps, in pure Python.

isotonic: pool-adjacent-violators gives a non-decreasing step function of the
raw probability. Blocks with fewer than `min_block` predictions are merged into
a neighbour, so no part of the map rests on a handful of markets (two lucky
85% predictions must not turn every 85% into 99%). It is applied by linear
interpolation between the blocks' centres, anchored at (0, 0) and (1, 1) beyond
the data instead of being held flat.

platt: calibrated = sigmoid(a * logit(p) + b), fitted by Newton's method on
Platt's smoothed targets ((n+ + 1)/(n+ + 2) and 1/(n- + 2)), which keeps a and b
finite even when the data are perfectly separable.
"""
from __future__ import annotations

import bisect
import math

EPS = 1e-4  # raw probabilities are clipped before taking logits


def logit(p: float) -> float:
    p = min(1 - EPS, max(EPS, p))
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def _merge(blocks: list, i: int, j: int) -> None:
    lo, hi = min(i, j), max(i, j)
    for k in range(3):
        blocks[lo][k] += blocks[hi][k]
    del blocks[hi]


def fit_isotonic(probs: list[float], outcomes: list[int], min_block: int = 20) -> dict:
    """Pool adjacent violators on (p, outcome) sorted by p, then merge blocks
    smaller than `min_block` into their closest neighbour (merging neighbours
    keeps the values non-decreasing). Equal probabilities start in one block,
    so their order never matters. Returns block centres `x`, values `y`, sizes `n`."""
    ties: dict[float, list[float]] = {}
    for p, o in zip(probs, outcomes):
        t = ties.setdefault(p, [0.0, 0.0, 0])
        t[0], t[1], t[2] = t[0] + p, t[1] + o, t[2] + 1
    blocks: list[list[float]] = []  # [sum_x, sum_y, n]
    for p in sorted(ties):
        blocks.append(ties[p])
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] >= blocks[-1][1] / blocks[-1][2]:
            _merge(blocks, len(blocks) - 2, len(blocks) - 1)
    value = lambda b: b[1] / b[2]  # noqa: E731
    while len(blocks) > 1:
        i = min(range(len(blocks)), key=lambda k: blocks[k][2])
        if blocks[i][2] >= min_block:
            break
        if i == 0 or (i < len(blocks) - 1 and
                      value(blocks[i + 1]) - value(blocks[i]) < value(blocks[i]) - value(blocks[i - 1])):
            _merge(blocks, i, i + 1)
        else:
            _merge(blocks, i, i - 1)
    return {"x": [b[0] / b[2] for b in blocks], "y": [value(b) for b in blocks], "n": [b[2] for b in blocks],
            "min_block": min_block}


def apply_isotonic(params: dict, p: float) -> float:
    xs, ys = [0.0, *params["x"], 1.0], [0.0, *params["y"], 1.0]
    p = min(1.0, max(0.0, p))
    i = min(max(bisect.bisect_right(xs, p), 1), len(xs) - 1)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (p - x0) / (x1 - x0)


def fit_platt(probs: list[float], outcomes: list[int], iterations: int = 100) -> dict:
    n_pos = sum(outcomes)
    n_neg = len(outcomes) - n_pos
    t_pos, t_neg = (n_pos + 1) / (n_pos + 2), 1 / (n_neg + 2)
    xs = [logit(p) for p in probs]
    ts = [t_pos if o else t_neg for o in outcomes]
    a, b = 1.0, 0.0

    def nll(a_, b_):
        total = 0.0
        for x, t in zip(xs, ts):
            q = min(1 - 1e-12, max(1e-12, sigmoid(a_ * x + b_)))
            total -= t * math.log(q) + (1 - t) * math.log(1 - q)
        return total

    loss = nll(a, b)
    for _ in range(iterations):
        ga = gb = haa = hab = hbb = 0.0
        for x, t in zip(xs, ts):
            q = sigmoid(a * x + b)
            d, w = q - t, q * (1 - q)
            ga += d * x
            gb += d
            haa += w * x * x
            hab += w * x
            hbb += w
        haa += 1e-9
        hbb += 1e-9
        det = haa * hbb - hab * hab
        if det <= 0:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        step = 1.0
        while step > 1e-6:  # halve the Newton step until the loss does not rise
            new = nll(a - step * da, b - step * db)
            if new <= loss:
                break
            step /= 2
        if step <= 1e-6:
            break
        a, b = a - step * da, b - step * db
        if loss - new < 1e-10:
            loss = new
            break
        loss = new
    return {"a": a, "b": b}


def apply_platt(params: dict, p: float) -> float:
    return sigmoid(params["a"] * logit(p) + params["b"])


FIT = {"isotonic": fit_isotonic, "platt": fit_platt}
APPLY = {"isotonic": apply_isotonic, "platt": apply_platt}


def calibrate(method: str, params: dict | None, p: float) -> float:
    """The calibrated probability; "identity" (or no params) returns p unchanged."""
    if method == "identity" or not params:
        return p
    return APPLY[method](params, p)
