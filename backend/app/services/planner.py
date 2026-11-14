"""FR-04 / FR-05: build a TOPTW problem from the request and solve it."""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from solver import GAConfig, Problem, Weights, describe, solve
from solver.problem import LOW_CONFIDENCE_TW_FACTOR

from .. import orm
from ..config import get_settings
from ..schemas import DayOut, ItineraryOut, OptimizeRequest, PlaceOut, StopOut
from .travel import travel_matrix

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


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


def closed_trip_days(req: OptimizeRequest, place: orm.Place) -> set[int]:
    """Trip days (0-based) on which the place is closed. Needs the trip's start date."""
    if req.start_date is None or not place.closed_days:
        return set()
    return {d for d in range(req.days) if (req.start_date + timedelta(days=d)).weekday() in place.closed_days}


def _name(place: orm.Place) -> str:
    return f"{place.label} · {place.ward}"


def optimize(req: OptimizeRequest, places: list[orm.Place]) -> ItineraryOut:
    locks = {lock.place_id: lock for lock in req.locks}
    closed = {p.id: closed_trip_days(req, p) for p in places}
    trip_warnings: list[str] = []

    # A place that is closed on every trip day cannot be scheduled, unless the user booked it.
    never_open = [p for p in places if len(closed[p.id]) == req.days and p.id not in locks]
    for p in never_open:
        trip_warnings.append(f"{_name(p)} is closed on every day of this trip")
    dropped = {p.id for p in never_open}
    places = [p for p in places if p.id not in dropped]
    if not places:
        raise ValueError("Every selected place is closed on the days of this trip")

    problem, source = build_problem(req, places)
    index = {p.id: i for i, p in enumerate(places)}
    seeds = None
    if req.seed_plan:
        days = [[index[pid] for pid in day if pid in index] for day in req.seed_plan[: req.days]]
        days += [[] for _ in range(req.days - len(days))]
        used = {i for d in days for i in d}
        seeds = [(days, [i for i in range(len(places)) if i not in used])]
    cfg = GAConfig(time_limit_s=get_settings().solver_time_limit_s, seed=7)
    result = solve(problem, cfg, seeds=seeds)

    # Closed weekdays (crawled opening hours). The solver has one window per place
    # for the whole trip, so a stop that lands on a closed day is pinned to an open
    # day and the plan is solved once more from there. solver/ stays untouched.
    def on_closed_day(days: list[list[int]]) -> list[tuple[int, int]]:
        return [(d, i) for d, seq in enumerate(days) for i in seq
                if d in closed[places[i].id] and places[i].id not in locks]

    moved: set[int] = set()
    if on_closed_day(result.days):
        plan = [list(seq) for seq in result.days]
        for d, i in on_closed_day(plan):
            plan[d].remove(i)
            target = min((t for t in range(req.days) if t not in closed[places[i].id]), key=lambda t: len(plan[t]))
            plan[target].append(i)
            moved.add(i)
        for d, seq in enumerate(plan):  # keep every day-sensitive stop on a day it is open
            for i in seq:
                if closed[places[i].id] and places[i].id not in locks:
                    problem.lock_day[i] = d
        result = solve(problem, cfg, seeds=[(plan, list(result.pool))])
        for d, i in on_closed_day(result.days):  # only a place that was unscheduled before can still land here
            result.days[d].remove(i)
            result.pool.append(i)
            trip_warnings.append(f"{_name(places[i])} is closed on day {d + 1} and did not fit on another day")
    for i in sorted(moved):
        if not any(i in seq for seq in result.days):
            continue
        days_closed = ", ".join(WEEKDAYS[w] for w in places[i].closed_days)
        trip_warnings.append(f"{_name(places[i])} is closed on {days_closed}; it was planned on a day it is open")

    if not req.locks and req.first_day_start is None and not any(closed.values()):
        # Days are interchangeable (same hours, same stay): fill day 1 first
        # instead of leaving it empty while later days hold the plan.
        result.days.sort(key=lambda d: len(d) == 0)
    schedule = describe(problem, result.days)

    days_out = []
    for day in schedule:
        stops, warnings = [], []
        for s in day.stops:
            place = places[s.index]
            close = problem.close[s.index]
            late = max(0, round(s.depart - close))
            lock = locks.get(place.id)
            if day.day in closed[place.id]:  # only possible for a place the user locked to this day
                warnings.append(f"{_name(place)} is usually closed on this day")
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
        unscheduled=[PlaceOut.model_validate(p) for p in [places[i] for i in result.pool] + never_open],
        warnings=trip_warnings,
        fitness=round(result.fitness, 2),
        generations=result.generations,
        runtime_s=round(result.runtime_s, 2),
        travel_source=source,
        weights={
            "w1_score": w.score, "w2_travel": w.travel, "w3_wait": w.wait,
            "w4_time_window": w.time_window, "w5_meal": w.meal, "w6_fatigue": w.fatigue,
        },
    )
