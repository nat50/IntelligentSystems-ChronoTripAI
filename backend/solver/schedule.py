"""Day simulation kernel: the single source of truth for timing and penalties.

`simulate_day` walks one day's visiting order, applies opening hours, golden
hours, meal rules and the fatigue rule, and returns the fitness components.
The GA calls it for every evaluation; the API calls it once more to produce the
detailed schedule shown to the user, so the two can never disagree.
"""

from __future__ import annotations

import numpy as np

from ._jit import njit
from .problem import (
    DINNER_WINDOW,
    GOLDEN_BONUS,
    HIGH_EFFORT,
    LUNCH_WINDOW,
    MEAL_MINUTES,
)

# Indices into the components vector returned by simulate_day
C_SCORE, C_TRAVEL, C_WAIT, C_TW, C_MEAL, C_FATIGUE, C_END = range(7)
N_COMPONENTS = 7

_MEAL_W0 = np.array([LUNCH_WINDOW[0], DINNER_WINDOW[0]], dtype=np.float64)
_MEAL_W1 = np.array([LUNCH_WINDOW[1], DINNER_WINDOW[1]], dtype=np.float64)


@njit(cache=True)
def simulate_day(
    seq,
    start_node,
    end_node,
    t0,
    t_end,
    travel,
    score,
    duration,
    open_,
    close,
    golden_start,
    golden_end,
    effort,
    is_food,
    soft_tw,
    lock_time,
    out_comp,
    out_stops,
):
    """Simulate one day.

    seq        int64[k]   POI indices in visiting order
    out_comp   float64[7] score, travel, wait, P_tw, P_meal, P_fatigue, return time
    out_stops  float64[k+1, 7] per stop: arrive, start, depart, wait, travel_in,
               golden(0/1), meal_break_before(min). Row k describes the return
               leg: arrive at end depot, -, -, -, travel_in, 0, meal break.
    """
    meal_w0 = np.empty(2)
    meal_w1 = np.empty(2)
    meal_w0[0] = 690.0
    meal_w1[0] = 810.0
    meal_w0[1] = 1080.0
    meal_w1[1] = 1230.0
    meal_len = 60.0

    needed = np.zeros(2, dtype=np.bool_)
    done = np.zeros(2, dtype=np.bool_)
    for j in range(2):
        # The day must cover the window with room for a meal
        needed[j] = (t0 <= meal_w1[j] - meal_len) and (t_end >= meal_w0[j] + meal_len)

    for c in range(7):
        out_comp[c] = 0.0

    t = t0
    prev = start_node
    prev_high = False
    k = seq.shape[0]

    for s in range(k + 1):
        is_return = s == k
        i = end_node if is_return else seq[s]
        food_next = (not is_return) and is_food[i] == 1

        # Meal break before leaving for the next place, when we are inside a
        # meal window and the next place does not serve the meal itself.
        brk = 0.0
        for j in range(2):
            if needed[j] and not done[j] and not food_next:
                if t >= meal_w0[j] and t <= meal_w1[j] - meal_len:
                    t += meal_len
                    brk += meal_len
                    done[j] = True
        if brk > 0.0:
            prev_high = False  # a meal break is also a rest

        tr = travel[prev, i]
        arr = t + tr
        out_comp[C_TRAVEL] += tr

        if is_return:
            # Back at the stay before a meal window closes: the traveller can eat there
            for j in range(2):
                if needed[j] and not done[j] and arr <= meal_w1[j] - meal_len:
                    done[j] = True
            if arr > t_end:
                over = arr - t_end
                out_comp[C_TW] += over * over
            out_stops[s, 0] = arr
            out_stops[s, 1] = arr
            out_stops[s, 2] = arr
            out_stops[s, 3] = 0.0
            out_stops[s, 4] = tr
            out_stops[s, 5] = 0.0
            out_stops[s, 6] = brk
            out_comp[C_END] = arr
            break

        start = arr
        if open_[i] > start:
            start = open_[i]
        lt = lock_time[i]
        if lt >= 0.0:
            if arr > lt:  # cannot make the booked time
                late = arr - lt
                out_comp[C_TW] += late * late
            elif lt > start:
                start = lt
        wait = start - arr
        out_comp[C_WAIT] += wait

        # A long wait inside a meal window can be used to eat
        if wait >= meal_len:
            for j in range(2):
                if needed[j] and not done[j]:
                    lo = arr if arr > meal_w0[j] else meal_w0[j]
                    hi = start if start < meal_w1[j] else meal_w1[j]
                    if hi - lo >= meal_len:
                        done[j] = True

        depart = start + duration[i]
        if depart > close[i]:
            over = depart - close[i]
            out_comp[C_TW] += soft_tw[i] * over * over

        golden = golden_start[i] <= start and start <= golden_end[i]
        beta = 1.25 if golden else 1.0
        out_comp[C_SCORE] += score[i] * beta

        if is_food[i] == 1:
            for j in range(2):
                if start >= meal_w0[j] and start <= meal_w1[j] - 30.0:
                    done[j] = True

        high = effort[i] >= 4
        if high and prev_high:
            out_comp[C_FATIGUE] += 1.0
        prev_high = high

        out_stops[s, 0] = arr
        out_stops[s, 1] = start
        out_stops[s, 2] = depart
        out_stops[s, 3] = wait
        out_stops[s, 4] = tr
        out_stops[s, 5] = 1.0 if golden else 0.0
        out_stops[s, 6] = brk

        t = depart
        prev = i

    for j in range(2):
        if needed[j] and not done[j]:
            out_comp[C_MEAL] += 1.0

    return out_comp[C_END]


@njit(cache=True)
def weighted(comp, w):
    return (
        w[0] * comp[0]
        - w[1] * comp[1]
        - w[2] * comp[2]
        - w[3] * comp[3]
        - w[4] * comp[4]
        - w[5] * comp[5]
    )


# Keep python-level constants and kernel literals in sync
assert _MEAL_W0[0] == 690.0 and _MEAL_W1[0] == 810.0
assert _MEAL_W0[1] == 1080.0 and _MEAL_W1[1] == 1230.0
assert MEAL_MINUTES == 60 and HIGH_EFFORT == 4 and GOLDEN_BONUS == 1.25
