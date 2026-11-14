"""FR-04 / FR-05: build a TOPTW problem from the request and solve it.

Also the parts of Figma T3 that sit around the solver: must-visit places, the
"No plan fits" fixes, progress for the "Building your itinerary" dialog, and the
optimizer settings applied from D4.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from datetime import timedelta

import numpy as np

from solver import GAConfig, Objective, Problem, Weights, describe, solve
from solver.problem import LOW_CONFIDENCE_TW_FACTOR

from .. import orm
from ..config import get_settings
from ..schemas import DayOut, ItineraryOut, OptimizerSettings, OptimizeRequest, PlaceOut, PlanFit, PlanFix, StopOut
from .travel import travel_matrix

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MUST_VISIT_BONUS = 1000.0  # added to S_i inside the solver only: a must-visit place outweighs any other stop
QUICK_TIME_LIMIT_S = 1.0  # quick re-optimizations that check each "No plan fits" fix
QUICK_GENERATIONS = 150
MEAL_ALLOWANCE = 60  # a longer day may cross a meal window, which costs a meal break
RETURN_ALLOWANCE = 30  # travel back to the stay after the last visit

# progress(event) -> False to cancel. Events: {"step": "hours" | "travel" | "search", ...}
ProgressFn = Callable[[dict], bool | None]


class Cancelled(Exception):
    """The traveler pressed Cancel while the plan was being computed."""


def _window_for_day(open_min: int, close_min: int, day_start: int, day_end: int) -> tuple[int, int]:
    """Pick the side of a midnight-wrapping window that overlaps the trip day most."""
    if close_min <= 24 * 60:
        return open_min, close_min
    shifted = (open_min - 24 * 60, close_min - 24 * 60)

    def overlap(a: int, b: int) -> int:
        return max(0, min(b, day_end) - max(a, day_start))

    return shifted if overlap(*shifted) > overlap(open_min, close_min) else (open_min, close_min)


def ga_config(settings: OptimizerSettings | None, quick: bool = False) -> GAConfig:
    st = settings or OptimizerSettings()
    limit = min(st.time_limit_s, get_settings().solver_time_limit_s)
    return GAConfig(
        population=st.population,
        max_generations=min(st.generations, QUICK_GENERATIONS) if quick else st.generations,
        crossover_p=st.crossover,
        mutation_p=st.mutation,
        local_search=st.local_search,
        time_limit_s=min(limit, QUICK_TIME_LIMIT_S) if quick else limit,
        seed=7,
    )


def build_problem(
    req: OptimizeRequest, places: list[orm.Place], settings: OptimizerSettings | None = None
) -> tuple[Problem, str]:
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

    objective = (settings or OptimizerSettings()).objective
    must = set(req.must_visit)
    problem = Problem(
        score=[p.score + (MUST_VISIT_BONUS if p.id in must else 0.0) for p in places],
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
        weights=Weights.from_preferences(
            req.preferences.pace, req.preferences.travel, req.preferences.strictness,
            Objective(objective.popularity, objective.golden, objective.travel),
        ),
    )
    return problem, source


def closed_trip_days(req: OptimizeRequest, place: orm.Place) -> set[int]:
    """Trip days (0-based) on which the place is closed. Needs the trip's start date."""
    if req.start_date is None or not place.closed_days:
        return set()
    return {d for d in range(req.days) if (req.start_date + timedelta(days=d)).weekday() in place.closed_days}


def route_travel(problem: Problem, days: list[list[int]]) -> float:
    """Total travel minutes of a plan, depot to depot."""
    total = 0.0
    for d, seq in enumerate(days):
        nodes = [int(problem.start_depot[d]), *seq, int(problem.end_depot[d])]
        total += float(sum(problem.travel[a, b] for a, b in zip(nodes, nodes[1:])))
    return total


def _name(place: orm.Place) -> str:
    return f"{place.label} · {place.ward}"


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def optimize(
    req: OptimizeRequest,
    places: list[orm.Place],
    settings: OptimizerSettings | None = None,
    progress: ProgressFn | None = None,
    quick: bool = False,
) -> ItineraryOut:
    """Solve the trip. `quick` runs a short search and skips the "No plan fits" fixes (used to test them)."""
    report = progress or (lambda event: None)
    all_places = places
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
    report({"step": "hours"})

    problem, source = build_problem(req, places, settings)
    if report({"step": "travel"}) is False:
        raise Cancelled()
    index = {p.id: i for i, p in enumerate(places)}
    seeds = None
    if req.seed_plan:
        days = [[index[pid] for pid in day if pid in index] for day in req.seed_plan[: req.days]]
        days += [[] for _ in range(req.days - len(days))]
        used = {i for d in days for i in d}
        seeds = [(days, [i for i in range(len(places)) if i not in used])]
    cfg = ga_config(settings, quick)
    cancelled = False

    def on_generation(gen: int, max_gen: int, best_days: list[list[int]]) -> bool:
        nonlocal cancelled
        keep_going = report({
            "step": "search", "generation": gen, "max_generations": max_gen,
            "stops": sum(len(d) for d in best_days), "travel": route_travel(problem, best_days),
        })
        cancelled = keep_going is False
        return not cancelled

    result = solve(problem, cfg, seeds=seeds, on_generation=on_generation)
    if cancelled:
        raise Cancelled()

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
        result = solve(problem, cfg, seeds=[(plan, list(result.pool))], on_generation=on_generation)
        if cancelled:
            raise Cancelled()
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
    # Describe and score the plan with the real S_i (the must-visit bonus only steers the search)
    shown = dataclasses.replace(problem, score=[p.score for p in places])
    schedule = describe(shown, result.days)

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
    out = ItineraryOut(
        days=days_out,
        unscheduled=[PlaceOut.model_validate(p) for p in [places[i] for i in result.pool] + never_open],
        warnings=trip_warnings,
        fitness=round(sum(d.fitness for d in schedule), 2),
        generations=result.generations,
        runtime_s=round(result.runtime_s, 2),
        travel_source=source,
        weights={
            "w1_score": w.score, "w2_travel": w.travel, "w3_wait": w.wait,
            "w4_time_window": w.time_window, "w5_meal": w.meal, "w6_fatigue": w.fatigue,
            "golden_bonus": w.golden,
        },
    )
    missing = [pid for pid in req.must_visit if pid in {p.id for p in out.unscheduled}]
    if missing and not quick:
        out.plan_fit = plan_fit(req, all_places, out, missing, settings)
    return out


# --------------------------------------------------------------------------- #
# "No plan fits" (Figma T3 state)
# --------------------------------------------------------------------------- #
def _patched(req: OptimizeRequest, patch: dict) -> OptimizeRequest:
    return OptimizeRequest.model_validate({**req.model_dump(mode="json"), **patch})


def _fits(req: OptimizeRequest, places: list[orm.Place], settings: OptimizerSettings | None) -> bool:
    by_id = {p.id: p for p in places}
    try:
        it = optimize(req, [by_id[pid] for pid in req.place_ids], settings, quick=True)
    except ValueError:
        return False
    scheduled = {s.place.id for d in it.days for s in d.stops}
    return set(req.must_visit) <= scheduled


def plan_fit(
    req: OptimizeRequest, places: list[orm.Place], it: ItineraryOut, missing: list[int],
    settings: OptimizerSettings | None,
) -> PlanFit:
    by_id = {p.id: p for p in places}
    locks = {lock.place_id: lock for lock in req.locks}
    span = req.day_end - req.day_start
    # one day is "too full" only when every missing place is locked to that same day
    locked_days = {locks[pid].day if pid in locks else None for pid in missing}
    day = next(iter(locked_days)) if len(locked_days) == 1 else None
    must = set(req.must_visit)
    if day is not None:
        on_day = {s.place.id for s in it.days[day].stops} if day < len(it.days) else set()
        ids = {pid for pid in must if pid in on_day or (pid in locks and locks[pid].day == day)}
        needed = sum(by_id[pid].duration for pid in ids)
        available = span - (it.days[day].travel_minutes if day < len(it.days) else 0)
    else:
        needed = sum(by_id[pid].duration for pid in must)
        available = sum(span - d.travel_minutes for d in it.days)
    shortfall = max(30, needed - available)

    candidates: list[tuple[str, str, dict]] = []
    # 1. move a locked must-visit place to the day with the most room
    for pid in missing:
        if pid not in locks or req.days == 1:
            continue
        room = {d.day: span - sum(s.depart - s.arrive for s in d.stops) for d in it.days if d.day != locks[pid].day}
        target = max(room, key=room.get)
        new_locks = [
            {"place_id": lk.place_id, "day": target, "start": None} if lk.place_id == pid else lk.model_dump()
            for lk in req.locks
        ]
        candidates.append(("move_place", f"Move {by_id[pid].label} to Day {target + 1}", {"locks": new_locks}))
    # 2. a longer day: enough for the missing visit time plus a meal break, and late
    #    enough for the missing places that only open in the afternoon or evening
    latest_visit = max(
        _window_for_day(by_id[pid].open_min, by_id[pid].close_min, req.day_start, req.day_end)[0] + by_id[pid].duration
        for pid in missing
    )
    wanted_end = max(req.day_end + shortfall + MEAL_ALLOWANCE, latest_visit + RETURN_ALLOWANCE)
    end = min(24 * 60, int(math.ceil(wanted_end / 30) * 30))
    if end > req.day_end:
        which = f"Day {day + 1}" if day is not None and req.days > 1 else ("the day" if req.days == 1 else "each day")
        candidates.append(("extend_day", f"Extend {which} to end at {_clock(end)}", {"day_end": end}))
    # 3. one more day
    if req.days < 3:
        candidates.append(("add_day", "Add one more day", {"days": req.days + 1}))
    # 4. drop the lowest-rated optional stops until the missing places have room
    optional = sorted(
        (s.place for d in it.days if day is None or d.day == day for s in d.stops if s.place.id not in must and s.place.id not in locks),
        key=lambda p: p.score,
    )
    drop, freed = [], 0
    need = sum(by_id[pid].duration for pid in missing)
    for p in optional:
        if freed >= need:
            break
        drop.append(p.id)
        freed += p.duration
    if drop and freed >= need:
        keep = [pid for pid in req.place_ids if pid not in drop]
        patch: dict = {"place_ids": keep}
        if req.seed_plan:
            patch["seed_plan"] = [[pid for pid in d if pid not in drop] for d in req.seed_plan]
        label = f"Remove {len(drop)} lower-rated stop{'s' if len(drop) > 1 else ''}"
        candidates.append(("drop_places", label, patch))

    fixes = [PlanFix(kind=k, label=lb, patch=p, fits=_fits(_patched(req, p), places, settings)) for k, lb, p in candidates]
    for f in fixes:  # the least disruptive fix that works, in the order above
        if f.fits:
            f.recommended = True
            break
    return PlanFit(missing=missing, day=day, needed_min=int(needed), available_min=int(available), fixes=fixes)
