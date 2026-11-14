"""Turn a solved visiting order into a detailed, human-readable schedule."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .problem import Problem
from .schedule import (
    C_FATIGUE,
    C_MEAL,
    C_SCORE,
    C_TRAVEL,
    C_TW,
    C_WAIT,
    N_COMPONENTS,
    simulate_day,
    weighted,
)


@dataclass
class ScheduledStop:
    index: int
    arrive: float
    start: float
    depart: float
    wait: float
    travel_in: float
    golden: bool
    meal_break_before: float


@dataclass
class DaySchedule:
    day: int
    stops: list[ScheduledStop]
    start_time: float
    return_time: float
    meal_break_before_return: float
    travel_minutes: float
    wait_minutes: float
    score: float
    time_window_penalty: float
    missed_meals: int
    fatigue_violations: int
    fitness: float


def describe(problem: Problem, days: list[list[int]]) -> list[DaySchedule]:
    p = problem
    w = p.weights.as_array()
    out: list[DaySchedule] = []
    for d, seq in enumerate(days):
        comp = np.zeros(N_COMPONENTS)
        stops = np.zeros((len(seq) + 1, 7))
        simulate_day(
            np.asarray(seq, dtype=np.int64), p.start_depot[d], p.end_depot[d], p.day_start[d], p.day_end[d],
            p.travel, p.score, p.duration, p.open_, p.close, p.golden_start, p.golden_end, p.effort,
            p.is_food, p.soft_tw, p.lock_time, p.weights.golden, comp, stops,
        )
        rows = [
            ScheduledStop(
                index=int(i),
                arrive=float(stops[k, 0]),
                start=float(stops[k, 1]),
                depart=float(stops[k, 2]),
                wait=float(stops[k, 3]),
                travel_in=float(stops[k, 4]),
                golden=bool(stops[k, 5] > 0.5),
                meal_break_before=float(stops[k, 6]),
            )
            for k, i in enumerate(seq)
        ]
        ret = stops[len(seq)]
        out.append(
            DaySchedule(
                day=d,
                stops=rows,
                start_time=float(p.day_start[d]),
                return_time=float(ret[0]),
                meal_break_before_return=float(ret[6]),
                travel_minutes=float(comp[C_TRAVEL]),
                wait_minutes=float(comp[C_WAIT]),
                score=float(comp[C_SCORE]),
                time_window_penalty=float(comp[C_TW]),
                missed_meals=int(comp[C_MEAL]),
                fatigue_violations=int(comp[C_FATIGUE]),
                fitness=float(weighted(comp, w)),
            )
        )
    return out
