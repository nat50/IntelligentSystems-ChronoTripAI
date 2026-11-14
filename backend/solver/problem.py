"""TOPTW problem definition (spec section III.1 - III.3).

All times are minutes since local midnight. Node indices 0..n-1 are POIs;
indices n.. are depots (stay / airport / station) in the travel matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Business rules (spec III.2.b)
LUNCH_WINDOW = (11 * 60 + 30, 13 * 60 + 30)
DINNER_WINDOW = (18 * 60, 20 * 60 + 30)
MEAL_MINUTES = 60
HIGH_EFFORT = 4  # spec III.2.c: no two consecutive places with e_i >= 4
GOLDEN_BONUS = 1.25  # Beta_i
LOW_CONFIDENCE_TW_FACTOR = 0.25  # low-confidence opening windows are soft


@dataclass(frozen=True)
class Objective:
    """Objective weights tuned on the optimizer screen (Figma D4), summing to 1.

    The defaults reproduce the spec weights. Each factor scales one part of F(X)
    relative to the defaults: popularity scales w1, golden scales the golden-hour
    bonus (Beta_i - 1), travel scales w2 and w3.
    """

    popularity: float = 0.6
    golden: float = 0.3
    travel: float = 0.1

    def factors(self) -> tuple[float, float, float]:
        total = self.popularity + self.golden + self.travel
        if total <= 0:
            return 1.0, 1.0, 1.0
        d = Objective()
        return (
            self.popularity / total / d.popularity,
            self.golden / total / d.golden,
            self.travel / total / d.travel,
        )


@dataclass(frozen=True)
class Weights:
    """w_1..w_6 of the fitness function F(X)."""

    score: float = 1.0  # w1  * sum(S_i * Beta_i)
    travel: float = 0.35  # w2  * T_travel (min)
    wait: float = 0.15  # w3  * T_wait (min)
    time_window: float = 0.30  # w4  * P_tw (squared minutes)
    meal: float = 60.0  # w5  * P_meal (missed meals)
    fatigue: float = 30.0  # w6  * P_fatigue (violations)
    golden: float = GOLDEN_BONUS - 1.0  # Beta_i - 1: extra score share for a start in the golden window

    @classmethod
    def from_preferences(
        cls, pace: float = 0.5, travel: float = 0.5, strictness: float = 0.5, objective: "Objective | None" = None
    ) -> "Weights":
        """Map the three preference sliders (each 0..1) to the weight vector w.

        pace:        0 = relaxed (fewer places, strong fatigue rule) .. 1 = packed
        travel:      0 = don't mind travelling .. 1 = keep travel short
        strictness:  0 = flexible hours/meals .. 1 = respect them strictly
        """
        pace, travel, strictness = (min(1.0, max(0.0, float(v))) for v in (pace, travel, strictness))
        o = (objective or Objective()).factors()
        return cls(
            score=(0.6 + 0.8 * pace) * o[0],
            travel=(0.15 + 0.65 * travel) * o[2],
            wait=(0.05 + 0.25 * travel) * o[2],
            time_window=0.02 + 0.56 * strictness,
            meal=20.0 + 80.0 * strictness,
            fatigue=60.0 - 45.0 * pace,
            golden=(GOLDEN_BONUS - 1.0) * o[1],
        )

    def as_array(self) -> np.ndarray:
        return np.array(
            [self.score, self.travel, self.wait, self.time_window, self.meal, self.fatigue], dtype=np.float64
        )


@dataclass
class Problem:
    score: np.ndarray  # S_i in [1, 100]
    duration: np.ndarray  # d_i minutes
    open_: np.ndarray  # O_i
    close: np.ndarray  # C_i
    golden_start: np.ndarray  # I_i^start
    golden_end: np.ndarray  # I_i^end
    effort: np.ndarray  # e_i in 1..5
    is_food: np.ndarray  # food place (satisfies a meal)
    soft_tw: np.ndarray  # penalty multiplier per place (low confidence => soft)
    travel: np.ndarray  # (n + n_depots) square matrix, minutes
    day_start: np.ndarray  # (m,)
    day_end: np.ndarray  # (m,)
    start_depot: np.ndarray  # (m,) matrix index of each day's start
    end_depot: np.ndarray  # (m,) matrix index of each day's end
    lat: np.ndarray
    lon: np.ndarray
    lock_day: np.ndarray = field(default=None)  # (n,) -1 = free
    lock_time: np.ndarray = field(default=None)  # (n,) -1 = no fixed start
    weights: Weights = field(default_factory=Weights)

    def __post_init__(self) -> None:
        n = len(self.score)
        f8 = lambda a: np.ascontiguousarray(a, dtype=np.float64)  # noqa: E731
        i8 = lambda a: np.ascontiguousarray(a, dtype=np.int64)  # noqa: E731
        self.score, self.duration = f8(self.score), f8(self.duration)
        self.open_, self.close = f8(self.open_), f8(self.close)
        self.golden_start, self.golden_end = f8(self.golden_start), f8(self.golden_end)
        self.effort, self.is_food = i8(self.effort), i8(self.is_food)
        self.soft_tw, self.travel = f8(self.soft_tw), f8(self.travel)
        self.day_start, self.day_end = f8(self.day_start), f8(self.day_end)
        self.start_depot, self.end_depot = i8(self.start_depot), i8(self.end_depot)
        self.lat, self.lon = f8(self.lat), f8(self.lon)
        self.lock_day = i8(np.full(n, -1) if self.lock_day is None else self.lock_day)
        self.lock_time = f8(np.full(n, -1.0) if self.lock_time is None else self.lock_time)
        if not 1 <= self.m <= 3:
            raise ValueError("Trips span 1 to 3 days")
        if n > 30:
            raise ValueError("At most 30 places per trip")
        if self.travel.shape[0] != self.travel.shape[1] or self.travel.shape[0] < n + 1:
            raise ValueError("Travel matrix must be square and include at least one depot")
        if np.any(self.lock_day >= self.m):
            raise ValueError("A place is locked to a day outside the trip")

    @property
    def n(self) -> int:
        return len(self.score)

    @property
    def m(self) -> int:
        return len(self.day_start)
