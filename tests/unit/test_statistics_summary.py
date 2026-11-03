"""mean_ci / paired_difference_ci / percentile against hand-computed values."""

from __future__ import annotations

import math

import pytest

from eval.statistics.summary import mean_ci, paired_difference_ci, percentile


class TestMeanCi:
    def test_three_values(self) -> None:
        result = mean_ci([1.0, 2.0, 3.0])
        assert result.mean == pytest.approx(2.0)
        assert result.n == 3
        # s = 1, t(0.975, 2) = 4.303 -> 4.303 / sqrt(3)
        assert result.half_width == pytest.approx(4.303 / math.sqrt(3))

    def test_single_value_has_no_interval(self) -> None:
        result = mean_ci([0.4])
        assert result.mean == pytest.approx(0.4)
        assert result.half_width is None
        assert result.render() == "0.400"

    def test_identical_values_have_zero_width(self) -> None:
        assert mean_ci([0.5, 0.5, 0.5]).half_width == pytest.approx(0.0)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            mean_ci([])

    def test_render_shows_interval(self) -> None:
        assert "+/-" in mean_ci([1.0, 2.0, 3.0]).render()

    def test_many_values_use_normal_critical_value(self) -> None:
        values = [float(i % 2) for i in range(40)]
        result = mean_ci(values)
        s = math.sqrt(sum((v - 0.5) ** 2 for v in values) / 39)
        assert result.half_width == pytest.approx(1.96 * s / math.sqrt(40))


class TestPairedDifference:
    def test_differences_are_per_pair(self) -> None:
        result = paired_difference_ci([0.9, 0.8, 0.7], [0.1, 0.2, 0.3])
        assert result.mean == pytest.approx(0.6)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            paired_difference_ci([1.0], [1.0, 2.0])


class TestPercentile:
    def test_median_of_odd_count(self) -> None:
        assert percentile([3.0, 1.0, 2.0], 50) == pytest.approx(2.0)

    def test_interpolates_between_ranks(self) -> None:
        assert percentile([0.0, 10.0], 25) == pytest.approx(2.5)

    def test_extremes(self) -> None:
        assert percentile([5.0, 1.0, 9.0], 0) == pytest.approx(1.0)
        assert percentile([5.0, 1.0, 9.0], 100) == pytest.approx(9.0)

    def test_invalid_q_raises(self) -> None:
        with pytest.raises(ValueError):
            percentile([1.0], 101)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            percentile([], 50)