"""Small, dependency-free summary statistics for multi-seed results.

README §8: every reported number carries a mean *and* a 95% confidence
interval across seeds, never a bare percentage. This module is deliberately
pure Python (no numpy/scipy) so it is trivial to test and audit.

Conventions:
- The CI is a two-sided 95% Student-t interval on the mean of per-seed
  values: mean +/- t(0.975, n-1) * s / sqrt(n), with s the sample std (n-1).
- With a single value there is no spread to estimate, so `half_width` is
  `None` (never 0.0, which would read as "perfectly certain").
- For n-1 > 30 degrees of freedom the normal value 1.96 is used; the error
  against the exact t value is under 4% of the half-width.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_T_975_BY_DF: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}  # fmt: skip
_Z_975: float = 1.960


@dataclass(frozen=True, slots=True)
class MeanCI:
    """Mean of n values with a 95% CI half-width (None when n < 2)."""

    mean: float
    half_width: float | None
    n: int

    def render(self, digits: int = 3) -> str:
        if self.half_width is None:
            return f"{self.mean:.{digits}f}"
        return f"{self.mean:.{digits}f} +/-{self.half_width:.{digits}f}"


def mean_ci(values: Sequence[float]) -> MeanCI:
    """Mean and 95% Student-t CI half-width of `values`."""
    n = len(values)
    if n == 0:
        raise ValueError("mean_ci requires at least one value")
    mean = sum(values) / n
    if n == 1:
        return MeanCI(mean=mean, half_width=None, n=1)
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    t_crit = _T_975_BY_DF.get(n - 1, _Z_975)
    return MeanCI(mean=mean, half_width=t_crit * math.sqrt(variance / n), n=n)


def paired_difference_ci(first: Sequence[float], second: Sequence[float]) -> MeanCI:
    """Mean and CI of `first[i] - second[i]` (paired by seed)."""
    if len(first) != len(second):
        raise ValueError("paired samples must have the same length")
    return mean_ci([a - b for a, b in zip(first, second, strict=True)])


def percentile(values: Sequence[float], q: float) -> float:
    """q-th percentile (0-100) with linear interpolation between ranks."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= q <= 100.0:
        raise ValueError("q must be in [0, 100]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


__all__ = ["MeanCI", "mean_ci", "paired_difference_ci", "percentile"]