"""Unit tests of the model helpers that do not need a trained version."""

import numpy as np
import pytest

from ml.hours import kind_group, parse_opening_hours
from ml.models import best_starts, hour_window, ndcg_at_k


def profile(peaks: dict[int, float], floor: float = 0.001) -> np.ndarray:
    p = np.full(24, floor)
    for hour, level in peaks.items():
        p[hour] = level
    return p / p.sum()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("24/7", (0, 1440, [])),
        ("Mo-Su 08:00-17:00", (480, 1020, [])),
        ("08:00-22:00", (480, 1320, [])),
        ("Tu-Su 08:00-11:30,13:30-17:00", (480, 1020, [0])),  # lunch break ignored
        ("Mo-Fr 08:00-17:00; Sa 08:00-12:00", (480, 1020, [6])),  # most common window
        ("Mo-Su 17:00-02:00", (1020, 1560, [])),  # past midnight
        ("We-Mo 08:30-17:30", (510, 1050, [1])),  # wrapping day range
        ("Mo-Su 09:00-18:00; Mo off; PH off", (540, 1080, [0])),
        ("Mo-Sun 07:00-22:00", (420, 1320, [])),
        ("Mo-Su,PH 08:00-22:00", (480, 1320, [])),
        ("Mo-Su 10:00-22:00+", (600, 1320, [])),
        ("Mo-Sa 07:00-19:00, Su 07:00-17:00", (420, 1140, [])),
        ("Mo-Sa 05:00-10:00, 14:00-21:00, Su 05:00-10:00", (300, 1260, [])),
    ],
)
def test_parse_opening_hours(text, expected):
    got = parse_opening_hours(text)
    assert (got["open_min"], got["close_min"], got["closed_days"]) == expected


@pytest.mark.parametrize("text", ["", "sunrise-sunset", "Apr-Oct Mo-Su 08:00-17:00", "by appointment", "Mo-Su off"])
def test_unusable_opening_hours_are_skipped(text):
    assert parse_opening_hours(text) is None


def test_osm_kinds_map_to_candidate_groups():
    assert kind_group("museum") == "sightseeing"
    assert kind_group("place_of_worship") == "sightseeing"
    assert kind_group("fast_food") == "food"
    assert kind_group("shop mall") == "shopping"
    assert kind_group("theme_park") == "entertainment"
    assert kind_group("nightclub") == "nightlife"
    assert kind_group("shop supermarket") is None


def test_estimated_window_stays_inside_one_business_day():
    # busy at dawn and at dusk: one long day, not a window across the night
    park = profile({6: 5, 7: 5, 17: 5, 18: 5}, floor=0.01)
    assert hour_window(park) == (6 * 60, 19 * 60)
    bar = profile({21: 4, 22: 5, 23: 5, 0: 4, 1: 2})
    assert hour_window(bar) == (21 * 60, 26 * 60)


def test_best_time_is_calm_for_sights_and_busy_for_food():
    p = profile({8: 2, 9: 3, 10: 4, 11: 6, 12: 9, 13: 10, 14: 8, 15: 6, 16: 4, 17: 3})[None, :]
    args = (np.array([8 * 60.0]), np.array([18 * 60.0]), np.array([60.0]))
    # the calmest two hours that are still lively (40% of the peak) and end before the 13:00 peak
    assert best_starts(p, np.array(["sightseeing"]), *args)[0] == 10
    assert best_starts(p, np.array(["food"]), *args)[0] == 12  # the peak itself
    # a visit that starts in the window must end before closing
    late = profile({8: 10, 9: 9, 10: 8, 15: 3, 16: 3, 17: 3})[None, :]
    start = best_starts(late, np.array(["shopping"]), *args)[0]
    assert start * 60 + 120 + 60 <= 18 * 60


def test_ndcg_rewards_the_right_top():
    gain = np.array([5.0, 4.0, 3.0, 0.0, 0.0])
    assert ndcg_at_k(gain, gain, k=3) == pytest.approx(1.0)
    assert ndcg_at_k(-gain, gain, k=3) < 0.5
