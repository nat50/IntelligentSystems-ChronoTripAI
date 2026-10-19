"""Memetic GA for TOPTW (spec section III.4, Table 3).

Chromosome: a permutation of POI genes 0..n-1 and M separator genes
n..n+M-1. The first M-1 separators split the days; everything after the M-th
separator is the reserve pool (places not scheduled). Because every
individual is a permutation of the same gene set, Order Crossover applies
directly. The lock mask (lock_day / lock_time) pins places to a day and,
optionally, to a booked start time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from .problem import Problem
from .schedule import C_END, N_COMPONENTS, simulate_day, weighted


@dataclass
class GAConfig:
    population: int = 100  # P
    kmeans_share: float = 0.30  # 30% geographic clustering, 70% random
    tournament_k: int = 4
    elite_share: float = 0.05
    crossover_p: float = 0.85
    mutation_p: float = 0.15
    local_search_every: int = 5
    local_search_share: float = 0.15
    max_generations: int = 400
    stagnation_limit: int = 80
    time_limit_s: float = 6.0
    seed: int | None = 7


@dataclass
class Individual:
    genes: np.ndarray
    fitness: float = -np.inf
    day_values: list[float] = field(default_factory=list)


@dataclass
class SolveResult:
    days: list[list[int]]
    pool: list[int]
    fitness: float
    generations: int
    runtime_s: float
    history: list[float]


class Evaluator:
    """Fitness F(X) with per-day caching (the fitness is additive over days)."""

    def __init__(self, p: Problem):
        self.p = p
        self.w = p.weights.as_array()
        self.comp = np.zeros(N_COMPONENTS)
        self.stops = np.zeros((p.n + 1, 7))
        self.cache: dict[tuple[int, tuple[int, ...]], float] = {}
        self.calls = 0

    def day_value(self, d: int, seq: list[int]) -> float:
        key = (d, tuple(seq))
        v = self.cache.get(key)
        if v is not None:
            return v
        self.calls += 1
        p = self.p
        simulate_day(
            np.asarray(seq, dtype=np.int64),
            p.start_depot[d],
            p.end_depot[d],
            p.day_start[d],
            p.day_end[d],
            p.travel,
            p.score,
            p.duration,
            p.open_,
            p.close,
            p.golden_start,
            p.golden_end,
            p.effort,
            p.is_food,
            p.soft_tw,
            p.lock_time,
            self.comp,
            self.stops,
        )
        v = float(weighted(self.comp, self.w))
        if len(self.cache) > 200_000:
            self.cache.clear()
        self.cache[key] = v
        return v

    def end_time(self, d: int, seq: list[int]) -> float:
        p = self.p
        simulate_day(
            np.asarray(seq, dtype=np.int64), p.start_depot[d], p.end_depot[d], p.day_start[d], p.day_end[d],
            p.travel, p.score, p.duration, p.open_, p.close, p.golden_start, p.golden_end, p.effort,
            p.is_food, p.soft_tw, p.lock_time, self.comp, self.stops,
        )
        return float(self.comp[C_END])

    def evaluate(self, ind: Individual) -> float:
        days, _ = split(ind.genes, self.p.n, self.p.m)
        ind.day_values = [self.day_value(d, seq) for d, seq in enumerate(days)]
        ind.fitness = float(sum(ind.day_values))
        return ind.fitness


# --------------------------------------------------------------------------- #
# Representation helpers
# --------------------------------------------------------------------------- #
def split(genes: np.ndarray, n: int, m: int) -> tuple[list[list[int]], list[int]]:
    days: list[list[int]] = [[] for _ in range(m)]
    pool: list[int] = []
    seg = 0
    for g in genes:
        g = int(g)
        if g >= n:
            seg += 1
            continue
        if seg < m:
            days[seg].append(g)
        else:
            pool.append(g)
    return days, pool


def join(days: list[list[int]], pool: list[int], n: int) -> np.ndarray:
    out: list[int] = []
    for d, seq in enumerate(days):
        out.extend(seq)
        out.append(n + d)
    out.extend(pool)
    return np.asarray(out, dtype=np.int64)


# --------------------------------------------------------------------------- #
# Memetic GA
# --------------------------------------------------------------------------- #
class MemeticGA:
    def __init__(self, problem: Problem, config: GAConfig | None = None):
        self.p = problem
        self.cfg = config or GAConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        self.ev = Evaluator(problem)
        self.free = [i for i in range(problem.n) if problem.lock_day[i] < 0]

    # ---- repair --------------------------------------------------------- #
    def repair(self, days: list[list[int]], pool: list[int]) -> tuple[list[list[int]], list[int]]:
        """Put every locked place on its day, ordering booked times correctly."""
        p = self.p
        for i in range(p.n):
            d = int(p.lock_day[i])
            if d < 0 or i in days[d]:
                continue
            for seq in days:
                if i in seq:
                    seq.remove(i)
            if i in pool:
                pool.remove(i)
            self._best_insert(days, d, i)
        # booked times must follow chronological order inside a day
        for d, seq in enumerate(days):
            timed = [i for i in seq if p.lock_time[i] >= 0]
            if len(timed) > 1:
                ordered = sorted(timed, key=lambda i: p.lock_time[i])
                slots = [k for k, i in enumerate(seq) if p.lock_time[i] >= 0]
                for k, i in zip(slots, ordered):
                    seq[k] = i
        return days, pool

    def _best_insert(self, days: list[list[int]], d: int, i: int) -> float:
        best_pos, best_val = 0, -np.inf
        seq = days[d]
        for pos in range(len(seq) + 1):
            cand = seq[:pos] + [i] + seq[pos:]
            v = self.ev.day_value(d, cand)
            if v > best_val:
                best_pos, best_val = pos, v
        seq.insert(best_pos, i)
        return best_val

    def _make(self, days: list[list[int]], pool: list[int]) -> Individual:
        days, pool = self.repair(days, pool)
        ind = Individual(join(days, pool, self.p.n))
        self.ev.evaluate(ind)
        return ind

    # ---- initialisation --------------------------------------------------- #
    def _kmeans(self, k: int) -> list[list[int]]:
        pts = np.column_stack([self.p.lat[self.free], self.p.lon[self.free]])
        if len(pts) == 0:
            return [[] for _ in range(k)]
        k_eff = min(k, len(pts))
        centers = pts[self.rng.choice(len(pts), k_eff, replace=False)]
        labels = np.zeros(len(pts), dtype=int)
        for _ in range(12):
            dist = ((pts[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
            labels = dist.argmin(1)
            for c in range(k_eff):
                if np.any(labels == c):
                    centers[c] = pts[labels == c].mean(0)
        clusters: list[list[int]] = [[] for _ in range(k)]
        order = self.rng.permutation(k)  # random cluster -> day assignment
        for idx, lab in enumerate(labels):
            clusters[order[lab]].append(self.free[idx])
        return clusters

    def _nearest_neighbour(self, d: int, items: list[int]) -> list[int]:
        cur = int(self.p.start_depot[d])
        left, seq = list(items), []
        while left:
            nxt = min(left, key=lambda j: self.p.travel[cur, j])
            seq.append(nxt)
            left.remove(nxt)
            cur = nxt
        return seq

    def _trim(self, days: list[list[int]], pool: list[int]) -> None:
        """Move low-value places to the pool until each day ends on time."""
        p = self.p
        for d, seq in enumerate(days):
            while seq and self.ev.end_time(d, seq) > p.day_end[d]:
                movable = [i for i in seq if p.lock_day[i] < 0]
                if not movable:
                    break
                worst = min(movable, key=lambda i: p.score[i] / max(p.duration[i], 1.0))
                seq.remove(worst)
                pool.append(worst)

    def _init_kmeans(self) -> Individual:
        m = self.p.m
        days = [self._nearest_neighbour(d, c) for d, c in enumerate(self._kmeans(m))]
        pool: list[int] = []
        days, pool = self.repair(days, pool)
        self._trim(days, pool)
        return self._make(days, pool)

    def _init_random(self) -> Individual:
        m = self.p.m
        days: list[list[int]] = [[] for _ in range(m)]
        pool: list[int] = []
        for i in self.rng.permutation(self.free):
            if self.rng.random() < 0.25:
                pool.append(int(i))
            else:
                days[int(self.rng.integers(m))].append(int(i))
        return self._make(days, pool)

    # ---- operators ---------------------------------------------------------- #
    def tournament(self, pop: list[Individual]) -> Individual:
        idx = self.rng.choice(len(pop), self.cfg.tournament_k, replace=False)
        return max((pop[i] for i in idx), key=lambda x: x.fitness)

    def la_ox1(self, a: Individual, b: Individual) -> Individual:
        """Lock-aware Order Crossover (OX1 + lock repair)."""
        g1, g2 = a.genes, b.genes
        size = len(g1)
        i, j = sorted(self.rng.choice(size + 1, 2, replace=False))
        child = np.full(size, -1, dtype=np.int64)
        child[i:j] = g1[i:j]
        taken = set(int(x) for x in g1[i:j])
        fill = [int(x) for x in np.concatenate([g2[j:], g2[:j]]) if int(x) not in taken]
        positions = list(range(j, size)) + list(range(0, i))
        for pos, gene in zip(positions, fill):
            child[pos] = gene
        days, pool = split(child, self.p.n, self.p.m)
        return self._make(days, pool)

    def mutate(self, ind: Individual) -> Individual:
        p, rng = self.p, self.rng
        days, pool = split(ind.genes, p.n, p.m)
        scheduled = [(d, k) for d, seq in enumerate(days) for k, i in enumerate(seq) if p.lock_day[i] < 0]
        op = int(rng.integers(4))
        if op == 0 and len(scheduled) >= 2:  # swap
            (d1, k1), (d2, k2) = (scheduled[x] for x in rng.choice(len(scheduled), 2, replace=False))
            days[d1][k1], days[d2][k2] = days[d2][k2], days[d1][k1]
        elif op == 1:  # inversion inside a day
            cands = [d for d, seq in enumerate(days) if len(seq) >= 2]
            if cands:
                d = int(rng.choice(cands))
                i, j = sorted(rng.choice(len(days[d]) + 1, 2, replace=False))
                days[d][i:j] = days[d][i:j][::-1]
        elif op == 2 and scheduled and p.m > 1:  # shift-day
            d, k = scheduled[int(rng.integers(len(scheduled)))]
            item = days[d].pop(k)
            target = int(rng.choice([x for x in range(p.m) if x != d]))
            days[target].insert(int(rng.integers(len(days[target]) + 1)), item)
        else:  # pool exchange
            if pool and (not scheduled or rng.random() < 0.5):
                item = pool.pop(int(rng.integers(len(pool))))
                if scheduled and rng.random() < 0.5:
                    d, k = scheduled[int(rng.integers(len(scheduled)))]
                    pool.append(days[d][k])
                    days[d][k] = item
                else:
                    self._best_insert(days, int(rng.integers(p.m)), item)
            elif scheduled:
                d, k = min(scheduled, key=lambda dk: p.score[days[dk[0]][dk[1]]])
                pool.append(days[d].pop(k))
        return self._make(days, pool)

    # ---- local search: 2-opt and Or-opt with time windows -------------------- #
    def local_search(self, ind: Individual, max_rounds: int = 3) -> Individual:
        p, ev = self.p, self.ev
        days, pool = split(ind.genes, p.n, p.m)
        vals = [ev.day_value(d, s) for d, s in enumerate(days)]
        for _ in range(max_rounds):
            improved = False
            # 2-opt inside each day
            for d in range(p.m):
                seq = days[d]
                for i in range(len(seq) - 1):
                    for j in range(i + 2, len(seq) + 1):
                        cand = seq[:i] + seq[i:j][::-1] + seq[j:]
                        v = ev.day_value(d, cand)
                        if v > vals[d] + 1e-9:
                            days[d], vals[d], seq, improved = cand, v, cand, True
            # Or-opt: move a segment of 1..3 places within or across days
            for d in range(p.m):
                for seg_len in (1, 2, 3):
                    k = 0
                    while k + seg_len <= len(days[d]):
                        seg = days[d][k : k + seg_len]
                        if any(p.lock_day[i] >= 0 and p.lock_day[i] != d for i in seg):
                            k += 1
                            continue
                        rest = days[d][:k] + days[d][k + seg_len :]
                        best = None
                        for t in range(p.m):
                            if t != d and any(p.lock_day[i] >= 0 for i in seg):
                                continue
                            base = rest if t == d else days[t]
                            for pos in range(len(base) + 1):
                                if t == d and pos == k:
                                    continue
                                cand_t = base[:pos] + seg + base[pos:]
                                if t == d:
                                    gain = ev.day_value(d, cand_t) - vals[d]
                                else:
                                    gain = ev.day_value(d, rest) + ev.day_value(t, cand_t) - vals[d] - vals[t]
                                if gain > 1e-9 and (best is None or gain > best[0]):
                                    best = (gain, t, cand_t)
                        if best:
                            _, t, cand_t = best
                            if t == d:
                                days[d] = cand_t
                            else:
                                days[d], days[t] = rest, cand_t
                                vals[t] = ev.day_value(t, cand_t)
                            vals[d] = ev.day_value(d, days[d])
                            improved = True
                        else:
                            k += 1
            # Or-opt from the reserve pool: insert a pooled place where it pays off
            for item in list(pool):
                best = None
                for t in range(p.m):
                    for pos in range(len(days[t]) + 1):
                        cand_t = days[t][:pos] + [item] + days[t][pos:]
                        gain = ev.day_value(t, cand_t) - vals[t]
                        if gain > 1e-9 and (best is None or gain > best[0]):
                            best = (gain, t, cand_t)
                if best:
                    _, t, cand_t = best
                    days[t], vals[t] = cand_t, ev.day_value(t, cand_t)
                    pool.remove(item)
                    improved = True
            # Drop places that cost more than they bring
            for d in range(p.m):
                for i in list(days[d]):
                    if p.lock_day[i] >= 0:
                        continue
                    cand = [x for x in days[d] if x != i]
                    v = ev.day_value(d, cand)
                    if v > vals[d] + 1e-9:
                        days[d], vals[d] = cand, v
                        pool.append(i)
                        improved = True
            if not improved:
                break
        return self._make(days, pool)

    # ---- main loop --------------------------------------------------------- #
    def run(self, seeds: list[tuple[list[list[int]], list[int]]] | None = None) -> SolveResult:
        cfg, p = self.cfg, self.p
        t_start = time.perf_counter()
        n_km = int(round(cfg.population * cfg.kmeans_share))
        pop: list[Individual] = [self._make([list(s) for s in d], list(pl)) for d, pl in (seeds or [])]
        while len(pop) < n_km:
            pop.append(self._init_kmeans())
        while len(pop) < cfg.population:
            pop.append(self._init_random())

        n_elite = max(1, int(round(cfg.population * cfg.elite_share)))
        best = max(pop, key=lambda x: x.fitness)
        history = [best.fitness]
        stagnant, gen = 0, 0
        for gen in range(1, cfg.max_generations + 1):
            pop.sort(key=lambda x: x.fitness, reverse=True)
            nxt = pop[:n_elite]
            while len(nxt) < cfg.population:
                a, b = self.tournament(pop), self.tournament(pop)
                child = self.la_ox1(a, b) if self.rng.random() < cfg.crossover_p else a
                if self.rng.random() < cfg.mutation_p:
                    child = self.mutate(child)
                nxt.append(child)
            pop = nxt
            if gen % cfg.local_search_every == 0:
                pop.sort(key=lambda x: x.fitness, reverse=True)
                n_ls = max(1, int(round(cfg.population * cfg.local_search_share)))
                pop[:n_ls] = [self.local_search(ind) for ind in pop[:n_ls]]
            gen_best = max(pop, key=lambda x: x.fitness)
            if gen_best.fitness > best.fitness + 1e-9:
                best, stagnant = gen_best, 0
            else:
                stagnant += 1
            history.append(best.fitness)
            if stagnant >= cfg.stagnation_limit or time.perf_counter() - t_start > cfg.time_limit_s:
                break

        best = self.local_search(best, max_rounds=6)
        days, pool = split(best.genes, p.n, p.m)
        return SolveResult(days, pool, best.fitness, gen, time.perf_counter() - t_start, history)


def solve(problem: Problem, config: GAConfig | None = None, seeds=None) -> SolveResult:
    return MemeticGA(problem, config).run(seeds)
