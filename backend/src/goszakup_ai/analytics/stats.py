import numpy as np
from numpy.typing import ArrayLike

MAD_TO_SIGMA = 1.4826


def weighted_quantile(values: ArrayLike, weights: ArrayLike, q: float) -> float:
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    order = np.argsort(v)
    v, w = v[order], w[order]
    cumulative = np.cumsum(w) / w.sum()
    i = int(np.searchsorted(cumulative, q, side="left"))
    if i < len(v) - 1 and np.isclose(cumulative[i], q):
        return float((v[i] + v[i + 1]) / 2)
    return float(v[min(i, len(v) - 1)])


def weighted_mean(values: ArrayLike, weights: ArrayLike) -> float:
    return float(np.average(np.asarray(values, dtype=float), weights=np.asarray(weights)))


def mad(values: ArrayLike) -> float:
    v = np.asarray(values, dtype=float)
    return float(np.median(np.abs(v - np.median(v))))


def robust_z_log(x: float, values: ArrayLike) -> float | None:
    logs = np.log(np.asarray(values, dtype=float))
    scale = MAD_TO_SIGMA * mad(logs)
    if scale <= 0:
        return None
    return float((np.log(x) - np.median(logs)) / scale)
