"""FR-04 / FR-05: build a TOPTW problem from the request and solve it."""

from __future__ import annotations

import numpy as np

from solver import GAConfig, Problem, Weights, describe, solve
from solver.problem import LOW_CONFIDENCE_TW_FACTOR

from .. import orm
from ..config import get_settings
from ..schemas import DayOut, ItineraryOut, OptimizeRequest, PlaceOut, StopOut
from .travel import travel_matrix


def _window_for_day(open_min: int, close_min: int, day_start: int, day_end: int) -> tuple[int, int]:
    """Pick the side of a midnight-wrapping window that overlaps the trip day most."""
    if close_min <= 24 * 60:
        return open_min, close_min
    shifted = (open_min - 24 * 60, close_min - 24 * 60)

    def overlap(a: int, b: int) -> int:
        return max(0, min(b, day_end) - max(a, day_start))

    return shifted if overlap(*shifted) > overlap(open_min, close_min) else (open_min, close_min)


def build_problem(req: OptimizeRequest, places: list[orm.Place]) -> tuple[Problem, str]:
    n, m = len(places), req.days
    windows = [_window_for_day(p.open_min, p.close_min, req.day_start, req.day_end) for p in places]
    lat = [p.lat for p in places] + [req.stay.lat]
    lon = [p.lon for p in places] + [req.stay.lon]
    start_depot = np.full(m, n)
    if req.first_day_start is not None:
        lat.append(req.first_day_start.lat)
        lon.append(req.first_day_start.lon)
        start_depot[0] = n + 1
    travel, source = travel_matrix(np.asarray(lat), np.asarray(lon))

    index = {p.id: i for i, p in enumerate(places)}
    lock_day = np.full(n, -1)
    lock_time = np.full(n, -1.0)
    for lock in req.locks:
        try:
            place_index = index[lock.place_id]
        except KeyError as exc:
            raise ValueError(f"Lock refers to a place that is not in the optimisation: {lock.place_id}") from exc
        lock_day[place_index] = lock.day
        if lock.start is not None:
            lock_time[place_index] = lock.start

    problem = Problem(
        score=[p.score for p in places],
        duration=[p.duration for p in places],
        open_=[w[0] for w in windows],
        close=[w[1] for w in windows],
        golden_start=[p.golden_start for p in places],
        golden_end=[p.golden_end for p in places],
        effort=[p.effort for p in places],
        is_food=[1 if p.group == "food" else 0 for p in places],
        soft_tw=[LOW_CONFIDENCE_TW_FACTOR if p.confidence == "low" else 1.0 for p in places],
        travel=travel,
        day_start=np.full(m, req.day_start),
        day_end=np.full(m, req.day_end),
        start_depot=start_depot,
        end_depot=np.full(m, n),
        lat=lat[:n],
        lon=lon[:n],
        lock_day=lock_day,
        lock_time=lock_time,
        weights=Weights.from_preferences(req.preferences.pace, req.preferences.travel, req.preferences.strictness),
    )
    return problem, source


def optimize(req: OptimizeRequest, places: list[orm.Place]) -> ItineraryOut:
    problem, source = build_problem(req, places)
    index = {p.id: i for i, p in enumerate(places)}
    seeds = None
    if req.seed_plan:
        days = [[index[pid] for pid in day] for day in req.seed_plan[: req.days]]
        days += [[] for _ in range(req.days - len(days))]
        used = {i for d in days for i in d}
        seeds = [(days, [i for i in range(len(places)) if i not in used])]
    cfg = GAConfig(time_limit_s=get_settings().solver_time_limit_s, seed=7)
    result = solve(problem, cfg, seeds=seeds)
    if not req.locks and req.first_day_start is None:
        # Days are interchangeable (same hours, same stay): fill day 1 first
        # instead of leaving it empty while later days hold the plan.
        result.days.sort(key=lambda d: len(d) == 0)
    schedule = describe(problem, result.days)
    locks = {lock.place_id: lock for lock in req.locks}

    days_out = []
    for day in schedule:
        stops, warnings = [], []
        for s in day.stops:
            place = places[s.index]
            close = problem.close[s.index]
            late = max(0, round(s.depart - close))
            lock = locks.get(place.id)
            if late > 0:
                warnings.append(f"{place.label} · {place.ward} may close about {late} min before you leave")
            if lock and lock.start is not None and s.arrive > lock.start + 1:
                warnings.append(f"You reach {place.label} · {place.ward} {round(s.arrive - lock.start)} min after the booked time")
            stops.append(
                StopOut(
                    place=PlaceOut.model_validate(place),
                    arrive=round(s.arrive),
                    start=round(s.start),
                    depart=round(s.depart),
                    wait=round(s.wait),
                    travel_in=round(s.travel_in),
                    golden=s.golden,
                    meal_break_before=round(s.meal_break_before),
                    locked=lock is not None,
                    locked_start=lock.start if lock else None,
                    late_by=late,
                )
            )
        if day.return_time > req.day_end + 1:
            warnings.append(f"Back about {round(day.return_time - req.day_end)} min after your day ends")
        if day.missed_meals:
            warnings.append("No time for a meal in one of the meal windows")
        if day.fatigue_violations:
            warnings.append("Two demanding places back to back")
        return_travel = problem.travel[day.stops[-1].index if day.stops else problem.start_depot[day.day], problem.end_depot[day.day]]
        days_out.append(
            DayOut(
                day=day.day,
                start=round(day.start_time),
                return_time=round(day.return_time),
                return_travel=round(float(return_travel)),
                meal_break_before_return=round(day.meal_break_before_return),
                travel_minutes=round(day.travel_minutes),
                wait_minutes=round(day.wait_minutes),
                stops=stops,
                warnings=warnings,
            )
        )
    w = problem.weights
    return ItineraryOut(
        days=days_out,
        unscheduled=[PlaceOut.model_validate(places[i]) for i in result.pool],
        fitness=round(result.fitness, 2),
        generations=result.generations,
        runtime_s=round(result.runtime_s, 2),
        travel_source=source,
        weights={
            "w1_score": w.score, "w2_travel": w.travel, "w3_wait": w.wait,
            "w4_time_window": w.time_window, "w5_meal": w.meal, "w6_fatigue": w.fatigue,
        },
    )
