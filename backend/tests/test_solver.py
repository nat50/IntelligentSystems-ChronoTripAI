import numpy as np
import pytest

from solver import GAConfig, Problem, Weights, describe, solve


def make_problem(n=20, m=2, seed=1, **kw) -> Problem:
    rng = np.random.default_rng(seed)
    lat = 10.80 + rng.normal(0, 0.02, n)
    lon = 106.75 + rng.normal(0, 0.02, n)
    pts = np.column_stack([np.append(lat, 10.80), np.append(lon, 106.75)])
    km = np.sqrt(((pts[:, None] - pts[None]) ** 2).sum(-1)) * 111.0
    travel = km / 25.0 * 60.0 + 5.0
    np.fill_diagonal(travel, 0.0)
    food = np.zeros(n, dtype=int)
    food[:4] = 1
    opens = np.full(n, 7 * 60.0)
    closes = np.full(n, 22 * 60.0)
    gs = rng.uniform(8 * 60, 18 * 60, n)
    args = dict(
        score=rng.uniform(20, 95, n),
        duration=rng.uniform(40, 100, n),
        open_=opens,
        close=closes,
        golden_start=gs,
        golden_end=gs + 120,
        effort=rng.integers(1, 6, n),
        is_food=food,
        soft_tw=np.ones(n),
        travel=travel,
        day_start=np.full(m, 8 * 60.0),
        day_end=np.full(m, 21 * 60.0 + 30),
        start_depot=np.full(m, n),
        end_depot=np.full(m, n),
        lat=lat,
        lon=lon,
        weights=Weights(),
    )
    args.update(kw)
    return Problem(**args)


FAST = GAConfig(population=40, max_generations=60, time_limit_s=10, seed=3)


def test_solution_is_a_partition_and_ends_on_time():
    p = make_problem()
    res = solve(p, FAST)
    seen = sorted([i for d in res.days for i in d] + res.pool)
    assert seen == list(range(p.n))
    for day in describe(p, res.days):
        # day end is a soft constraint (squared penalty), small overruns are allowed
        assert day.return_time <= p.day_end[day.day] + 10
        for a, b in zip(day.stops, day.stops[1:]):
            assert b.arrive >= a.depart - 1e-6


def test_ga_beats_random_order():
    p = make_problem(seed=5)
    res = solve(p, FAST)
    rng = np.random.default_rng(0)
    from solver.memetic import Evaluator

    ev = Evaluator(p)
    rand = rng.permutation(p.n)
    naive = [list(rand[: p.n // 2]), list(rand[p.n // 2 :])]
    naive_val = sum(ev.day_value(d, [int(x) for x in s]) for d, s in enumerate(naive))
    assert res.fitness > naive_val


def test_locks_are_respected():
    n = 16
    lock_day = np.full(n, -1)
    lock_time = np.full(n, -1.0)
    lock_day[3], lock_time[3] = 1, 14 * 60.0
    lock_day[7] = 0
    p = make_problem(n=n, lock_day=lock_day, lock_time=lock_time)
    res = solve(p, FAST)
    assert 3 in res.days[1] and 7 in res.days[0]
    sched = describe(p, res.days)
    stop = next(s for s in sched[1].stops if s.index == 3)
    assert stop.start == pytest.approx(14 * 60.0) or stop.arrive > 14 * 60.0


def test_meal_rule_is_satisfied():
    p = make_problem(seed=11)
    res = solve(p, FAST)
    assert all(day.missed_meals == 0 for day in describe(p, res.days))


def test_no_back_to_back_strenuous_places():
    n = 14
    p = make_problem(n=n, effort=np.array([5, 5, 5, 5, 5, 5, 1, 1, 1, 1, 2, 2, 2, 2]), m=1)
    res = solve(p, FAST)
    assert describe(p, res.days)[0].fatigue_violations == 0


def test_validation():
    with pytest.raises(ValueError):
        make_problem(n=31)
