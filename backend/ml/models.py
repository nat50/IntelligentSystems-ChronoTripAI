"""The three attribute models of spec section IV.1 (Table 4).

M1  Popularity     -> S_i            LightGBM on log(1 + distinct users), trained on rolling cut-offs,
                                     Spearman / NDCG@20 vs raw-count baseline
M2  Hour profile   -> best time, estimated opening window
                                     hierarchical Dirichlet-Multinomial (category > city > ward > venue),
                                     circular smoothing, log-likelihood vs category prior
M3  Visit length   -> d_i (+ range)  quantile gradient boosting (q25 / q50 / q75),
                                     MAE / RMSE / within 15 min vs category median

Every metric is also reported for the served cities and by amount of history
(0-9, 10-29, 30+ check-ins), because Vietnamese venues have very little data.
See docs/model-changes.md for what changed and why.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .categories import GROUP_PRIORS, GROUPS
from .geo import SUPPORTED_CITIES
from .preprocess import TRAIN_END

HOURS = 24
BUCKETS = (("0-9", 0, 10), ("10-29", 10, 30), ("30+", 30, np.inf))
PEAK_GROUPS = ("food", "nightlife")  # best time = busiest hours (meal time, night out)
BEST_MINUTES = 120
QUIET_FLOOR = 0.4  # a quiet window still needs this share of the peak-hour level
DAY_BREAK_H = 4  # 04:00, where one business day ends and the next begins
WINDOW_MASS = 0.9  # share of check-ins inside the estimated opening window

# Settings each model accepts from the data console (Figma D3 "Edit settings"):
# name -> (default, min, max). Anything else is rejected.
SETTINGS: dict[str, dict[str, tuple[float, float, float]]] = {
    "m1": {"learning_rate": (0.05, 0.005, 0.5), "num_leaves": (63, 7, 255), "n_cutoffs": (5, 1, 8)},
    "m2": {"quiet_floor": (QUIET_FLOOR, 0.0, 0.9), "window_mass": (WINDOW_MASS, 0.5, 0.99)},
    "m3": {"learning_rate": (0.05, 0.005, 0.5), "num_leaves": (31, 7, 255)},
}
INTEGER_SETTINGS = {"num_leaves", "n_cutoffs"}


def check_settings(model: str, given: dict) -> dict:
    """Defaults filled in, unknown keys and out-of-range values rejected (ValueError)."""
    spec = SETTINGS[model]
    unknown = sorted(set(given) - set(spec))
    if unknown:
        raise ValueError(f"Unknown {model} settings: {unknown}. Allowed: {sorted(spec)}")
    out = {}
    for name, (default, lo, hi) in spec.items():
        value = float(given.get(name, default))
        if not lo <= value <= hi:
            raise ValueError(f"{model}.{name} must be between {lo} and {hi}")
        out[name] = int(round(value)) if name in INTEGER_SETTINGS else value
    return out
STABLE_HIGH, STABLE_MEDIUM = 0.8, 0.5  # share of posterior draws that agree with the estimate


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return float("nan")
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def ndcg_at_k(pred: np.ndarray, gain: np.ndarray, k: int = 20) -> float:
    """How much of the best possible top-k gain the predicted top-k collects."""
    if len(pred) == 0:
        return float("nan")
    k = min(k, len(pred))
    disc = 1.0 / np.log2(np.arange(2, k + 2))
    ideal = float((np.sort(gain)[::-1][:k] * disc).sum())
    if ideal <= 0:
        return float("nan")
    return float((gain[np.argsort(-pred, kind="stable")[:k]] * disc).sum() / ideal)


def pinball(y: np.ndarray, q: np.ndarray, alpha: float = 0.5) -> float:
    diff = y - q
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def level(value: np.ndarray, high: float, medium: float) -> np.ndarray:
    return np.where(value >= high, "high", np.where(value >= medium, "medium", "low"))


def bucket_masks(n: np.ndarray) -> dict[str, np.ndarray]:
    return {name: (n >= lo) & (n < hi) for name, lo, hi in BUCKETS}


def history_counts(n_venues: int, checkins: pd.DataFrame, mask: pd.Series) -> np.ndarray:
    return np.bincount(checkins.loc[mask, "venue_idx"].to_numpy(), minlength=n_venues)


def _months(split_mask: pd.Series, local: pd.Series) -> float:
    if not split_mask.any():
        return 1.0
    span = local[split_mask].max() - local[split_mask].min()
    return max(span / pd.Timedelta(days=30.4), 1.0)


def _codes(values: pd.Series, vocab: list[str]) -> np.ndarray:
    lookup = {v: i for i, v in enumerate(vocab)}
    return values.map(lambda x: lookup.get(x, -1)).to_numpy(dtype=np.int32)


def _cell(venues: pd.DataFrame, size: float) -> np.ndarray:
    """Integer id of the lat/lon grid cell (0.005 deg is about 500 m)."""
    lat = np.floor(venues["lat"].to_numpy() / size).astype(np.int64)
    lon = np.floor(venues["lon"].to_numpy() / size).astype(np.int64)
    return lat * 1_000_000 + lon


def _area_key(venues: pd.DataFrame) -> pd.Series:
    """label | city | ward: the smallest area a venue shares with similar places."""
    ward = venues["ward"].fillna("") if "ward" in venues else ""
    return venues["label"].fillna("") + "|" + venues["city"].fillna("") + "|" + ward


def _mean_of_others(value: pd.Series, key) -> np.ndarray:
    """Mean of `value` over the other venues with the same key (NaN if alone)."""
    g = value.groupby(np.asarray(key))
    total, count = g.transform("sum"), g.transform("size")
    return ((total - value) / (count - 1).where(count > 1)).to_numpy()


# --------------------------------------------------------------------------- #
# M1 - popularity
# --------------------------------------------------------------------------- #
@dataclass
class M1Popularity:
    booster: lgb.Booster | None = None
    labels: list[str] | None = None
    cities: list[str] | None = None
    learning_rate: float = 0.05
    num_leaves: int = 63
    n_cutoffs: int = 5  # rolling origins, two months apart, the last one at TRAIN_END

    FEATURES = [
        "label_code", "group_code", "city_code", "lat", "lon",
        "density_500m", "density_2km", "users_pm", "checkins_pm", "users_recent_pm",
        "weekend_share", "hour_sin", "hour_cos", "one_time_share",
        # do not depend on the venue's own history: they carry the cold-start venues
        "nbr_users_500m", "nbr_users_2km", "area_users",
    ]
    HORIZON = pd.DateOffset(months=2)
    RECENT = pd.Timedelta(days=91)

    def features(self, venues: pd.DataFrame, checkins: pd.DataFrame, period_mask: pd.Series) -> pd.DataFrame:
        df = pd.DataFrame(index=venues.index)
        df["label_code"] = _codes(venues["label"], self.labels)
        df["group_code"] = _codes(venues["group"].fillna(""), list(GROUPS))
        df["city_code"] = _codes(venues["city"].fillna(""), self.cities)
        df["lat"], df["lon"] = venues["lat"].to_numpy(), venues["lon"].to_numpy()
        cand = venues["group"].notna()
        cells = {"500m": pd.Series(_cell(venues, 0.005), index=venues.index),
                 "2km": pd.Series(_cell(venues, 0.02), index=venues.index)}
        for name, key in cells.items():
            df[f"density_{name}"] = key.map(key[cand].value_counts()).fillna(0).to_numpy()

        c = checkins[period_mask]
        months = _months(period_mask, checkins["local"])
        hours = c["local"].dt.hour.to_numpy() * (2 * np.pi / 24)
        c = c.assign(hs=np.sin(hours), hc=np.cos(hours), we=c["local"].dt.dayofweek.ge(5).to_numpy())
        g = c.groupby("venue_idx")
        per_user = c.groupby(["venue_idx", "user"]).size()
        recent = c[c["local"] >= c["local"].max() - self.RECENT] if len(c) else c
        agg = pd.DataFrame(
            {
                "users_pm": g["user"].nunique() / months,
                "checkins_pm": g.size() / months,
                "users_recent_pm": recent.groupby("venue_idx")["user"].nunique() / 3.0,
                "weekend_share": g["we"].mean(),
                "hour_sin": g["hs"].mean(),
                "hour_cos": g["hc"].mean(),
                "one_time_share": (per_user == 1).groupby(level=0).mean(),
            }
        )
        df = df.join(agg)
        counts = ["users_pm", "checkins_pm", "users_recent_pm"]
        df[counts] = df[counts].fillna(0)
        df["nbr_users_500m"] = _mean_of_others(df["users_pm"], cells["500m"])
        df["nbr_users_2km"] = _mean_of_others(df["users_pm"], cells["2km"])
        df["area_users"] = _mean_of_others(df["users_pm"], _area_key(venues))
        return df[self.FEATURES]

    @staticmethod
    def target(venues: pd.DataFrame, checkins: pd.DataFrame, period_mask: pd.Series) -> pd.Series:
        users = checkins[period_mask].groupby("venue_idx")["user"].nunique()
        return np.log1p(users.reindex(venues.index).fillna(0))

    def fit(self, venues: pd.DataFrame, checkins: pd.DataFrame, seed: int = 0) -> dict:
        self.labels = sorted(venues["label"].dropna().unique().tolist())
        self.cities = sorted(venues["city"].dropna().unique().tolist())
        split, local = checkins["split"], checkins["local"]
        cand = venues["group"].notna().to_numpy()
        rng = np.random.default_rng(seed)
        hold_venue = (rng.random(len(venues)) < 0.2)[cand]  # a venue is on one side at every cut-off

        # Rolling origins: history before T -> distinct users in the two months after T.
        # Every target window ends at or before VAL_END, so the test period stays unseen.
        Xs, ys, holds = [], [], []
        for k in reversed(range(self.n_cutoffs)):
            t = TRAIN_END - pd.DateOffset(months=2 * k)
            past, future = local < t, (local >= t) & (local < t + self.HORIZON)
            if not past.any() or not future.any():
                continue
            Xs.append(self.features(venues, checkins, past)[cand])
            ys.append(self.target(venues, checkins, future)[cand])
            holds.append(hold_venue)
        if not Xs:  # degenerate data set: fall back to the single train -> val pair
            Xs = [self.features(venues, checkins, split == "train")[cand]]
            ys = [self.target(venues, checkins, split == "val")[cand]]
            holds = [hold_venue]
        X, y, hold = pd.concat(Xs, ignore_index=True), pd.concat(ys, ignore_index=True), np.concatenate(holds)

        params = dict(
            objective="regression", learning_rate=self.learning_rate, num_leaves=self.num_leaves,
            min_data_in_leaf=max(5, len(X) // 2500), feature_fraction=0.9, bagging_fraction=0.8,
            bagging_freq=1, seed=seed, verbose=-1,
        )
        cat = ["label_code", "group_code", "city_code"]
        dtr = lgb.Dataset(X[~hold], y[~hold], categorical_feature=cat, free_raw_data=False)
        dva = lgb.Dataset(X[hold], y[hold], categorical_feature=cat, reference=dtr)
        self.booster = lgb.train(
            params, dtr, num_boost_round=2000, valid_sets=[dva],
            callbacks=[lgb.early_stopping(100, verbose=False)],
        )

        # Test: features from train+val, target from the test period
        X_te = self.features(venues, checkins, split != "test")[cand]
        y_te = self.target(venues, checkins, split == "test")[cand].to_numpy()
        pred = self.booster.predict(X_te)
        base = X_te["users_pm"].to_numpy()
        active = y_te > 0
        v = venues[cand]
        vn = (v["cc"] == "VN").to_numpy()
        history = history_counts(len(venues), checkins, split != "test")[cand]

        def rank_metrics(m: np.ndarray) -> dict:
            return {
                "spearman": spearman(pred[m], y_te[m]),
                "spearman_baseline": spearman(base[m], y_te[m]),
                "ndcg20": ndcg_at_k(pred[m], y_te[m]),
                "ndcg20_baseline": ndcg_at_k(base[m], y_te[m]),
                "n": int(m.sum()),
            }

        served = v["city"].isin(SUPPORTED_CITIES).to_numpy()
        by_city = {c: rank_metrics((v["city"] == c).to_numpy()) for c in SUPPORTED_CITIES}
        return {
            "spearman": spearman(pred[active], y_te[active]),
            "spearman_baseline": spearman(base[active], y_te[active]),
            "spearman_all": spearman(pred, y_te),
            "spearman_all_baseline": spearman(base, y_te),
            "spearman_vn": spearman(pred[vn], y_te[vn]),
            "spearman_vn_baseline": spearman(base[vn], y_te[vn]),
            "ndcg20": float(np.nanmean([m["ndcg20"] for m in by_city.values()])),
            "ndcg20_baseline": float(np.nanmean([m["ndcg20_baseline"] for m in by_city.values()])),
            "by_city": by_city,
            # buckets inside the served cities: this is where the app is used
            "by_bucket": {name: rank_metrics(m & served) for name, m in bucket_masks(history).items()},
            "n_train": int((~hold).sum()),
            "n_cutoffs": len(Xs),
            "best_iteration": int(self.booster.best_iteration or 0),
        }

    def predict(self, venues: pd.DataFrame, checkins: pd.DataFrame) -> np.ndarray:
        X = self.features(venues, checkins, pd.Series(True, index=checkins.index))
        return self.booster.predict(X)

    def save(self, d: Path) -> None:
        self.booster.save_model(str(d / "m1.txt"))
        (d / "m1.json").write_text(json.dumps({"labels": self.labels, "cities": self.cities}))

    @classmethod
    def load(cls, d: Path) -> "M1Popularity":
        meta = json.loads((d / "m1.json").read_text())
        return cls(lgb.Booster(model_file=str(d / "m1.txt")), meta["labels"], meta["cities"])

    def save_settings(self) -> dict:
        return {"learning_rate": self.learning_rate, "num_leaves": self.num_leaves, "n_cutoffs": self.n_cutoffs}


# --------------------------------------------------------------------------- #
# M2 - hour profile (hierarchical Dirichlet-Multinomial)
# --------------------------------------------------------------------------- #
def circular_smooth(p: np.ndarray, width: float = 1.0) -> np.ndarray:
    """Convolve hour histograms with a wrapped Gaussian kernel (24 h circle)."""
    offs = np.arange(-3, 4)
    k = np.exp(-0.5 * (offs / width) ** 2)
    k /= k.sum()
    out = np.zeros_like(p, dtype=float)
    for o, w in zip(offs, k):
        out += w * np.roll(p, o, axis=-1)
    return out


def hour_windows(p: np.ndarray, mass: float = 0.9) -> tuple[np.ndarray, np.ndarray]:
    """Per row: start hour and length (hours) of the shortest run holding `mass`.

    The run lies inside one "business day" from DAY_BREAK_H to DAY_BREAK_H + 24,
    so a bar can run past midnight, but a park that is busy at dawn and at dusk
    gets 05:00-19:00 and not the shorter-looking 16:00-09:00 across the night.
    """
    p = np.roll(p / p.sum(1, keepdims=True), -DAY_BREAK_H, axis=1)
    n = len(p)
    cum = np.concatenate([np.zeros((n, 1)), p.cumsum(1)], axis=1)
    start, length = np.zeros(n, dtype=np.int64), np.full(n, HOURS, dtype=np.int64)
    done = np.zeros(n, dtype=bool)
    rows = np.arange(n)
    for run in range(1, HOURS + 1):
        sums = cum[:, run:] - cum[:, : HOURS + 1 - run]
        s = sums.argmax(1)
        ok = ~done & (sums[rows, s] >= mass - 1e-9)
        start[ok], length[ok] = s[ok], run
        done |= ok
    return (start + DAY_BREAK_H) % HOURS, length


def hour_window(p: np.ndarray, mass: float = 0.9) -> tuple[int, int]:
    """Shortest circular run of whole hours holding `mass` of the profile (minutes)."""
    s, run = hour_windows(np.asarray(p, dtype=float)[None, :], mass)
    return int(s[0]) * 60, int(s[0] + run[0]) * 60


def _window_level(p: np.ndarray, minutes: int) -> np.ndarray:
    """Mean hourly level of the window starting at each hour, shape (n, 24)."""
    h = minutes // 60
    ext = np.concatenate([p, p], axis=1)
    return sum(ext[:, j : j + HOURS] for j in range(h)) / h


def busiest_starts(p: np.ndarray, minutes: int = BEST_MINUTES) -> np.ndarray:
    return _window_level(p, minutes).argmax(1)


def best_starts(
    p: np.ndarray, groups: np.ndarray, open_min: np.ndarray, close_min: np.ndarray, duration: np.ndarray,
    minutes: int = BEST_MINUTES, floor: float = QUIET_FLOOR,
) -> np.ndarray:
    """Start hour of the best window to arrive, always inside the opening hours.

    Food and nightlife: the busiest window (meal time, a full bar).
    Everything else (Figma T2 / D2, "open and below the daily peak"): the calmest
    window before the daily peak in which a visit still ends before closing. The
    window must reach `floor` of the peak-hour level, which keeps out the dead
    hours at the edges of the day. If no window before the peak qualifies, the
    calmest qualifying window of the day is used.
    """
    lvl = _window_level(p, minutes)
    peak = p.max(1, keepdims=True)
    starts = np.arange(HOURS) * 60
    op, cl, du = open_min[:, None], close_min[:, None], duration[:, None]

    def fits(tail):
        return np.logical_or.reduce(
            [(starts + shift >= op) & (starts + shift + minutes + tail <= cl) for shift in (0, 24 * 60)]
        )

    strict, loose = fits(du), fits(0)
    allowed = np.where(strict.any(1, keepdims=True), strict, loose)
    busiest = np.where(allowed.any(1), np.where(allowed, lvl, -np.inf).argmax(1), lvl.argmax(1))

    lively = allowed & (lvl >= floor * peak)
    since_open = (starts - op) % (24 * 60)
    peak_since_open = (p.argmax(1)[:, None] * 60 - op) % (24 * 60)
    early = lively & (since_open + minutes <= peak_since_open)  # the window ends as the peak hour starts
    calm = np.where(early.any(1, keepdims=True), early, lively)
    calmest = np.where(calm, lvl, np.inf).argmin(1)
    quiet = np.where(calm.any(1), calmest, busiest)
    return np.where(np.isin(groups, PEAK_GROUPS), busiest, quiet)


def golden_window(p: np.ndarray, minutes: int = BEST_MINUTES) -> tuple[int, int]:
    """Busiest window of one profile (kept for food / nightlife and for callers of the old API)."""
    s = int(busiest_starts(np.asarray(p, dtype=float)[None, :], minutes)[0])
    return s * 60, s * 60 + minutes


def _hour_gap(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = np.abs(a - b) % HOURS
    return np.minimum(d, HOURS - d)


@dataclass
class M2HourProfile:
    kappa_venue: float = 10.0
    kappa_city: float = 20.0
    kappa_cat: float = 20.0
    width: float = 1.0
    global_p: np.ndarray | None = None
    cat_p: dict | None = None
    city_p: dict | None = None
    kappa_ward: float = 20.0
    ward_p: dict | None = None  # "label|city|ward" -> profile (the regional prior)
    quiet_floor: float = QUIET_FLOOR  # used when the best time is picked from the profile
    window_mass: float = WINDOW_MASS  # used when the opening window is estimated from it

    @staticmethod
    def _hist(checkins: pd.DataFrame, venues: pd.DataFrame, mask: pd.Series) -> np.ndarray:
        c = checkins[mask]
        flat = c["venue_idx"].to_numpy().astype(np.int64) * HOURS + c["local"].dt.hour.to_numpy()
        counts = np.bincount(flat, minlength=len(venues) * HOURS)
        return counts.reshape(len(venues), HOURS).astype(np.float32)

    def _fit_priors(self, venues: pd.DataFrame, hist: np.ndarray) -> None:
        """category <- city <- ward: each level is shrunk towards the one above it."""
        tot = hist.sum(0) + 1.0
        self.global_p = tot / tot.sum()
        lab = venues["label"].fillna("").to_numpy()
        city = venues["city"].fillna("").to_numpy()
        ward = venues["ward"].fillna("").to_numpy() if "ward" in venues else np.full(len(venues), "")
        df = pd.DataFrame(hist.astype(np.float64))

        def shrink(h: np.ndarray, parent: np.ndarray, kappa: float) -> np.ndarray:
            return (h + kappa * parent) / (h.sum() + kappa)

        self.cat_p = {
            c: shrink(h.to_numpy(), self.global_p, self.kappa_cat) for c, h in df.groupby(lab).sum().iterrows()
        }
        self.city_p = {
            f"{c}|{ci}": shrink(h.to_numpy(), self.cat_p[c], self.kappa_city)
            for (c, ci), h in df.groupby([lab, city]).sum().iterrows()
        }
        has_ward = ward != ""
        self.ward_p = {}
        if has_ward.any():
            sums = df[has_ward].groupby([lab[has_ward], city[has_ward], ward[has_ward]]).sum()
            self.ward_p = {
                f"{c}|{ci}|{w}": shrink(h.to_numpy(), self.city_p[f"{c}|{ci}"], self.kappa_ward)
                for (c, ci, w), h in sums.iterrows()
            }

    def _prior(self, key: str) -> np.ndarray:
        lab, city, ward = key.split("|", 2)
        p = self.ward_p.get(key) if ward and self.ward_p else None
        if p is None:
            p = self.city_p.get(f"{lab}|{city}")
        if p is None:
            p = self.cat_p.get(lab, self.global_p)
        return p

    def parent(self, venues: pd.DataFrame) -> np.ndarray:
        codes, keys = pd.factorize(_area_key(venues))
        return np.stack([self._prior(k) for k in keys])[codes]

    def alpha(self, venues: pd.DataFrame, hist: np.ndarray, kappa: float | None = None,
              parent: np.ndarray | None = None) -> np.ndarray:
        """Dirichlet posterior parameters of each venue's hour profile."""
        kappa = self.kappa_venue if kappa is None else kappa
        return hist + kappa * (self.parent(venues) if parent is None else parent)

    def posterior(self, venues: pd.DataFrame, hist: np.ndarray, kappa: float | None = None,
                  parent: np.ndarray | None = None) -> np.ndarray:
        p = circular_smooth(self.alpha(venues, hist, kappa, parent), self.width)
        return p / p.sum(1, keepdims=True)

    @staticmethod
    def loglik(p: np.ndarray, hist: np.ndarray) -> float:
        n = hist.sum()
        return float((hist * np.log(np.clip(p, 1e-12, None))).sum() / max(n, 1))

    def fit(self, venues: pd.DataFrame, checkins: pd.DataFrame) -> dict:
        split = checkins["split"]
        h_tr = self._hist(checkins, venues, split == "train")
        h_va = self._hist(checkins, venues, split == "val")
        h_te = self._hist(checkins, venues, split == "test")
        # choose the concentrations and the smoothing width on validation log-likelihood
        best = None
        for kappa_ward in (5.0, 20.0, 80.0, 1e9):  # 1e9 switches the ward level off
            self.kappa_ward = kappa_ward
            self._fit_priors(venues, h_tr)
            par = self.parent(venues)
            for kappa in (1, 3, 10, 30, 100):
                for width in (0.75, 1.0, 1.5):
                    self.width = width
                    ll = self.loglik(self.posterior(venues, h_tr, kappa, par), h_va)
                    if best is None or ll > best[0]:
                        best = (ll, kappa, width, kappa_ward)
        _, self.kappa_venue, self.width, self.kappa_ward = best
        # refit priors on train+val, evaluate on test
        h_trva = h_tr + h_va
        self._fit_priors(venues, h_trva)
        p_model = self.posterior(venues, h_trva)
        prior = np.stack([self.cat_p.get(lb, self.global_p) for lb in venues["label"].fillna("")])
        p_base = circular_smooth(prior, self.width)

        def ll_metrics(m: np.ndarray) -> dict:
            return {
                "loglik": self.loglik(p_model[m], h_te[m]),
                "loglik_baseline": self.loglik(p_base[m], h_te[m]),
                "n_checkins": int(h_te[m].sum()),
            }

        city = venues["city"].to_numpy()
        served = np.isin(city, SUPPORTED_CITIES)
        return {
            "loglik": self.loglik(p_model, h_te),
            "loglik_baseline": self.loglik(p_base, h_te),
            "by_city": {c: ll_metrics(city == c) for c in SUPPORTED_CITIES},
            "by_bucket": {name: ll_metrics(m & served) for name, m in bucket_masks(h_trva.sum(1)).items()},
            "kappa_venue": float(self.kappa_venue),
            "kappa_ward": float(self.kappa_ward),
            "width": float(self.width),
        }

    def stability(
        self, alpha: np.ndarray, groups: np.ndarray, open_min: np.ndarray, close_min: np.ndarray,
        duration: np.ndarray, draws: int = 30, tolerance_h: int = 1, seed: int = 0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Share of posterior draws whose best time / opening window stays within
        `tolerance_h` of the point estimate. Few check-ins and a vague prior give
        draws that disagree, which is what "low confidence" should mean."""
        rng = np.random.default_rng(seed)

        def estimate(p):
            start, run = hour_windows(p, self.window_mass)
            return best_starts(p, groups, open_min, close_min, duration, floor=self.quiet_floor), start, start + run

        mean = circular_smooth(alpha, self.width)
        ref = estimate(mean / mean.sum(1, keepdims=True))
        best_ok, window_ok = np.zeros(len(alpha)), np.zeros(len(alpha))
        for _ in range(draws):
            g = rng.standard_gamma(alpha) + 1e-12
            p = circular_smooth(g / g.sum(1, keepdims=True), self.width)
            best, start, end = estimate(p / p.sum(1, keepdims=True))
            best_ok += _hour_gap(best, ref[0]) <= tolerance_h
            window_ok += (_hour_gap(start, ref[1]) <= tolerance_h) & (_hour_gap(end, ref[2]) <= tolerance_h)
        return best_ok / draws, window_ok / draws

    def save(self, d: Path) -> None:
        def table(prefix: str, src: dict | None) -> dict:
            src = src or {}
            vals = np.array(list(src.values())) if src else np.zeros((0, HOURS))
            return {f"{prefix}_keys": np.array(list(src), dtype=str), f"{prefix}_vals": vals}

        np.savez(
            d / "m2.npz",
            global_p=self.global_p,
            **table("cat", self.cat_p), **table("city", self.city_p), **table("ward", self.ward_p),
            params=np.array([
                self.kappa_venue, self.kappa_city, self.kappa_cat, self.width, self.kappa_ward,
                self.quiet_floor, self.window_mass,
            ]),
        )

    @classmethod
    def load(cls, d: Path) -> "M2HourProfile":
        z = np.load(d / "m2.npz", allow_pickle=False)
        params = z["params"].tolist()
        kv, kc, kcat, w = params[:4]
        m = cls(kv, kc, kcat, w, z["global_p"])
        m.cat_p = dict(zip(z["cat_keys"].tolist(), z["cat_vals"]))
        m.city_p = dict(zip(z["city_keys"].tolist(), z["city_vals"]))
        m.ward_p = dict(zip(z["ward_keys"].tolist(), z["ward_vals"])) if "ward_keys" in z else {}
        m.kappa_ward = params[4] if len(params) > 4 else m.kappa_ward
        if len(params) > 6:
            m.quiet_floor, m.window_mass = params[5], params[6]
        return m

    def save_settings(self) -> dict:
        return {"quiet_floor": float(self.quiet_floor), "window_mass": float(self.window_mass)}


# --------------------------------------------------------------------------- #
# M3 - visit length (quantile gradient boosting)
# --------------------------------------------------------------------------- #
@dataclass
class M3VisitLength:
    booster: lgb.Booster | None = None  # the median (q50)
    labels: list[str] | None = None
    cities: list[str] | None = None
    alpha: float = 0.5
    category_median: dict | None = None
    lower: lgb.Booster | None = None  # q25
    upper: lgb.Booster | None = None  # q75
    learning_rate: float = 0.05
    num_leaves: int = 31

    FEATURES = [
        "label_code", "group_code", "city_code", "hour", "weekend", "log_users",
        "effort", "density_500m", "venue_dwell", "log_visits",
    ]
    QUANTILES = (0.25, 0.5, 0.75)
    SHRINK = 5.0  # pseudo-visits of the parent level in the venue encoding
    FOLDS = 5
    MIN_EVAL_VISITS = 3

    def encode(self, venues: pd.DataFrame, visits: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Typical dwell of every venue (minutes) and its number of visits.

        Mean of log-dwell, shrunk venue -> label x city -> label -> all, so a venue
        with two visits stays close to similar places in its city.
        """
        k = self.SHRINK
        idx = visits["venue_idx"].to_numpy()
        logd = np.log(np.maximum(visits["dwell"].to_numpy(dtype=np.float64), 1.0))
        n = len(venues)
        overall = float(logd.mean()) if len(logd) else float(np.log(60.0))
        lab_code, _ = pd.factorize(venues["label"].fillna(""))
        lc_code, _ = pd.factorize(venues["label"].fillna("") + "|" + venues["city"].fillna(""))

        def level_mean(code: np.ndarray, parent: np.ndarray) -> np.ndarray:
            size = int(code.max()) + 1 if len(code) else 0
            s = np.bincount(code[idx], weights=logd, minlength=size)
            c = np.bincount(code[idx], minlength=size)
            parent_of_group = np.zeros(size)
            parent_of_group[code] = parent  # constant inside a group
            return ((s + k * parent_of_group) / (c + k))[code]

        by_label = level_mean(lab_code, np.full(n, overall))
        by_label_city = level_mean(lc_code, by_label)
        s = np.bincount(idx, weights=logd, minlength=n)
        c = np.bincount(idx, minlength=n)
        return np.exp((s + k * by_label_city) / (c + k)), c.astype(np.float64)

    def _frame(self, venues: pd.DataFrame, venue_idx: np.ndarray, hour: np.ndarray, weekend: np.ndarray,
               dwell: np.ndarray, count: np.ndarray) -> pd.DataFrame:
        v = venues.iloc[venue_idx]
        cell = pd.Series(_cell(venues, 0.005))
        density = cell.map(cell.value_counts()).to_numpy()
        return pd.DataFrame(
            {
                "label_code": _codes(v["label"], self.labels),
                "group_code": _codes(v["group"].fillna(""), list(GROUPS)),
                "city_code": _codes(v["city"].fillna(""), self.cities),
                "hour": np.asarray(hour).astype(np.int16),
                "weekend": np.asarray(weekend).astype(np.int8),
                "log_users": np.log1p(v["n_users"].to_numpy()),
                "effort": v["effort"].to_numpy(),
                "density_500m": density[venue_idx],
                "venue_dwell": dwell,
                "log_visits": np.log1p(count),
            }
        )

    def _rows(self, venues: pd.DataFrame, s: pd.DataFrame, dwell: np.ndarray, count: np.ndarray) -> pd.DataFrame:
        idx = s["venue_idx"].to_numpy()
        return self._frame(
            venues, idx, s["local"].dt.hour.to_numpy(), s["local"].dt.dayofweek.ge(5).to_numpy(), dwell[idx], count[idx]
        )

    def fit(self, venues: pd.DataFrame, visits: pd.DataFrame, seed: int = 0) -> dict:
        self.labels = sorted(venues["label"].dropna().unique().tolist())
        self.cities = sorted(venues["city"].dropna().unique().tolist())
        cand = venues["group"].notna().to_numpy()
        vis = visits[cand[visits["venue_idx"].to_numpy()]]
        s_tr, s_va, s_te = (vis[vis["split"] == name] for name in ("train", "val", "test"))
        y_tr, y_va, y_te = (s["dwell"].to_numpy() for s in (s_tr, s_va, s_te))

        # Training rows get an out-of-fold encoding, otherwise each row would see its own dwell.
        fold = np.random.default_rng(seed).integers(0, self.FOLDS, len(s_tr))
        idx_tr = s_tr["venue_idx"].to_numpy()
        enc_tr, cnt_tr = np.empty(len(s_tr)), np.empty(len(s_tr))
        for f in range(self.FOLDS):
            dwell, count = self.encode(venues, s_tr[fold != f])
            m = fold == f
            enc_tr[m], cnt_tr[m] = dwell[idx_tr[m]], count[idx_tr[m]] * self.FOLDS / (self.FOLDS - 1)
        X_tr = self._frame(
            venues, idx_tr, s_tr["local"].dt.hour.to_numpy(), s_tr["local"].dt.dayofweek.ge(5).to_numpy(), enc_tr, cnt_tr
        )
        X_va = self._rows(venues, s_va, *self.encode(venues, s_tr))
        X_te = self._rows(venues, s_te, *self.encode(venues, vis[vis["split"] != "test"]))

        cat = ["label_code", "group_code", "city_code"]
        dtr = lgb.Dataset(X_tr, y_tr, categorical_feature=cat, free_raw_data=False)
        valid, names = [dtr], ["train"]
        if len(X_va):
            valid.append(lgb.Dataset(X_va, y_va, categorical_feature=cat, reference=dtr))
            names.append("valid")
        boosters, curve = {}, {}
        for q in self.QUANTILES:
            params = dict(
                objective="quantile", alpha=q, learning_rate=self.learning_rate, num_leaves=self.num_leaves,
                min_data_in_leaf=max(5, len(X_tr) // 1000), seed=seed, verbose=-1,
            )
            history: dict = {}
            cbs = [lgb.record_evaluation(history)]
            if len(X_va):
                cbs.append(lgb.early_stopping(100, verbose=False))
            boosters[q] = lgb.train(
                params, dtr, num_boost_round=1500 if len(X_va) else 300, valid_sets=valid, valid_names=names,
                callbacks=cbs,
            )
            if q == self.alpha:
                curve = history
        self.lower, self.booster, self.upper = (boosters[q] for q in self.QUANTILES)

        labels_tr = venues["label"].to_numpy()[idx_tr]
        self.category_median = pd.Series(y_tr).groupby(labels_tr).median().to_dict()
        metrics = {"n_train": int(len(X_tr)), "best_iteration": int(self.booster.best_iteration or 0)}
        metrics["learning_curve"] = self._curve(curve)
        if not len(y_te):
            return metrics | {"pinball": float("nan"), "pinball_baseline": float("nan")}

        q = self._predict(X_te)
        idx_te = s_te["venue_idx"].to_numpy()
        fallback = float(np.median(y_tr))
        base = np.array([self.category_median.get(lb, fallback) for lb in venues["label"].to_numpy()[idx_te]])
        metrics |= {
            "pinball": pinball(y_te, q[:, 1], self.alpha),
            "pinball_baseline": pinball(y_te, base, self.alpha),
            "coverage_50": float(np.mean((y_te >= q[:, 0]) & (y_te <= q[:, 2]))),
        }

        # D3 metrics per venue: median observed dwell in the test period vs the estimate.
        per = pd.DataFrame({"venue": idx_te, "y": y_te, "pred": q[:, 1], "base": base}).groupby("venue").agg(
            y=("y", "median"), pred=("pred", "median"), base=("base", "median"), n=("y", "size")
        )
        v = venues.iloc[per.index]
        per["city"], per["label"], per["ward"] = v["city"].to_numpy(), v["label"].to_numpy(), v["ward"].to_numpy()
        per["history"] = v["n_checkins"].to_numpy()
        served = per["city"].isin(SUPPORTED_CITIES).to_numpy()
        metrics |= self._errors(per)
        metrics["by_city"] = {c: self._errors(per[(per["city"] == c).to_numpy()]) for c in SUPPORTED_CITIES}
        metrics["by_bucket"] = {
            name: self._errors(per[m & served]) for name, m in bucket_masks(per["history"].to_numpy()).items()
        }
        shown = per[served & (per["n"] >= self.MIN_EVAL_VISITS)]
        shown = shown if len(shown) else per[per["n"] >= self.MIN_EVAL_VISITS]
        err = (shown["pred"] - shown["y"]).round()
        metrics["largest_errors"] = [
            {
                "place": f"{r.label} · {r.ward or r.city}", "city": r.city, "error_min": int(e),
                "actual_min": int(round(r.y)), "predicted_min": int(round(r.pred)), "n_visits": int(r.n),
            }
            for r, e in ((shown.loc[i], err[i]) for i in err.abs().sort_values(ascending=False).index[:5])
        ]
        return metrics

    def _errors(self, per: pd.DataFrame) -> dict:
        """MAE / RMSE / share within 15 min over venues with enough test visits."""
        min_visits = self.MIN_EVAL_VISITS
        kept = per[per["n"] >= min_visits]
        if len(kept) < 20:  # too few venues with repeated visits: use every visited venue
            min_visits, kept = 1, per
        out: dict = {"n_venues": int(len(kept)), "min_visits": min_visits}
        for suffix, col in (("", "pred"), ("_baseline", "base")):
            e = (kept[col] - kept["y"]).to_numpy()
            out |= {
                f"mae{suffix}": float(np.abs(e).mean()) if len(e) else float("nan"),
                f"rmse{suffix}": float(np.sqrt((e**2).mean())) if len(e) else float("nan"),
                f"within_15{suffix}": float((np.abs(e) <= 15).mean()) if len(e) else float("nan"),
            }
        return out

    @staticmethod
    def _curve(history: dict, points: int = 60) -> dict:
        """Pinball loss (minutes) per boosting round, thinned to at most `points` rounds."""
        series = {name: next(iter(vals.values())) for name, vals in history.items()}
        rounds = len(next(iter(series.values()), []))
        step = max(1, rounds // points)
        keep = list(range(0, rounds, step))
        return {"iteration": [i + 1 for i in keep]} | {
            name: [round(float(vals[i]), 3) for i in keep] for name, vals in series.items()
        }

    def _predict(self, X: pd.DataFrame) -> np.ndarray:
        """Columns q25, q50, q75, forced to be ordered."""
        models = (self.lower or self.booster, self.booster, self.upper or self.booster)
        return np.sort(np.stack([m.predict(X) for m in models], axis=1), axis=1)

    def predict_venues(self, venues: pd.DataFrame, visits: pd.DataFrame, idx: np.ndarray, hour: np.ndarray) -> np.ndarray:
        """q25 / q50 / q75 of the visit length at venues `idx`, for a weekday visit at `hour`."""
        dwell, count = self.encode(venues, visits)
        X = self._frame(venues, idx, hour, np.zeros(len(idx)), dwell[idx], count[idx])
        return self._predict(X)

    def save(self, d: Path) -> None:
        self.booster.save_model(str(d / "m3.txt"))
        self.lower.save_model(str(d / "m3_q25.txt"))
        self.upper.save_model(str(d / "m3_q75.txt"))
        (d / "m3.json").write_text(
            json.dumps({"labels": self.labels, "cities": self.cities, "alpha": self.alpha, "category_median": self.category_median})
        )

    @classmethod
    def load(cls, d: Path) -> "M3VisitLength":
        meta = json.loads((d / "m3.json").read_text())

        def booster(name: str) -> lgb.Booster | None:
            return lgb.Booster(model_file=str(d / name)) if (d / name).exists() else None

        return cls(
            booster("m3.txt"), meta["labels"], meta["cities"], meta["alpha"], meta["category_median"],
            booster("m3_q25.txt"), booster("m3_q75.txt"),
        )

    def save_settings(self) -> dict:
        return {"learning_rate": self.learning_rate, "num_leaves": self.num_leaves}


def fallback_duration(group: str | None) -> float:
    return float(GROUP_PRIORS.get(group or "", GROUP_PRIORS["sightseeing"])["duration"])
