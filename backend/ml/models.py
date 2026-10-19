"""The three attribute models of spec section IV.1 (Table 4).

M1  Popularity     -> S_i            LightGBM on log(1 + distinct users), Spearman vs raw-count baseline
M2  Hour profile   -> [O_i, C_i], [I_start, I_end]
                                     hierarchical Dirichlet-Multinomial, circular smoothing,
                                     log-likelihood vs category prior
M3  Visit length   -> d_i            quantile gradient boosting, pinball loss vs category median
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .categories import GROUP_PRIORS

HOURS = 24


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


def pinball(y: np.ndarray, q: np.ndarray, alpha: float = 0.5) -> float:
    diff = y - q
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def _months(split_mask: pd.Series, local: pd.Series) -> float:
    if not split_mask.any():
        return 1.0
    span = local[split_mask].max() - local[split_mask].min()
    return max(span / pd.Timedelta(days=30.4), 1.0)


def _codes(values: pd.Series, vocab: list[str]) -> np.ndarray:
    lookup = {v: i for i, v in enumerate(vocab)}
    return values.map(lambda x: lookup.get(x, -1)).to_numpy(dtype=np.int32)


# --------------------------------------------------------------------------- #
# M1 - popularity
# --------------------------------------------------------------------------- #
@dataclass
class M1Popularity:
    booster: lgb.Booster | None = None
    labels: list[str] | None = None
    cities: list[str] | None = None

    FEATURES = [
        "label_code", "group_code", "city_code", "lat", "lon",
        "density_500m", "density_2km", "users_pm", "checkins_pm", "weekend_share", "hour_sin", "hour_cos",
    ]

    def features(self, venues: pd.DataFrame, checkins: pd.DataFrame, period_mask: pd.Series) -> pd.DataFrame:
        cand = venues["group"].notna()
        lat, lon = venues["lat"].to_numpy(), venues["lon"].to_numpy()
        df = pd.DataFrame(index=venues.index)
        df["label_code"] = _codes(venues["label"], self.labels)
        df["group_code"] = _codes(venues["group"].fillna(""), ["sightseeing", "entertainment", "food", "nightlife", "shopping"])
        df["city_code"] = _codes(venues["city"].fillna(""), self.cities)
        df["lat"], df["lon"] = lat, lon
        for name, cell in (("density_500m", 0.005), ("density_2km", 0.02)):
            key = pd.Series(list(zip(np.floor(lat / cell), np.floor(lon / cell))), index=venues.index)
            counts = key[cand].value_counts()
            df[name] = key.map(counts).fillna(0).to_numpy()
        c = checkins[period_mask]
        months = _months(period_mask, checkins["local"])
        hours = c["local"].dt.hour.to_numpy() * (2 * np.pi / 24)
        c = c.assign(hs=np.sin(hours), hc=np.cos(hours), we=c["local"].dt.dayofweek.ge(5).to_numpy())
        g = c.groupby("venue_idx")
        agg = pd.DataFrame(
            {
                "users_pm": g["user"].nunique() / months,
                "checkins_pm": g.size() / months,
                "weekend_share": g["we"].mean(),
                "hour_sin": g["hs"].mean(),
                "hour_cos": g["hc"].mean(),
            }
        )
        df = df.join(agg)
        df[["users_pm", "checkins_pm"]] = df[["users_pm", "checkins_pm"]].fillna(0)
        return df[self.FEATURES]

    @staticmethod
    def target(venues: pd.DataFrame, checkins: pd.DataFrame, period_mask: pd.Series) -> pd.Series:
        users = checkins[period_mask].groupby("venue_idx")["user"].nunique()
        return np.log1p(users.reindex(venues.index).fillna(0))

    def fit(self, venues: pd.DataFrame, checkins: pd.DataFrame, seed: int = 0) -> dict:
        self.labels = sorted(venues["label"].dropna().unique().tolist())
        self.cities = sorted(venues["city"].dropna().unique().tolist())
        split = checkins["split"]
        cand = venues["group"].notna().to_numpy()
        X = self.features(venues, checkins, split == "train")[cand]
        y = self.target(venues, checkins, split == "val")[cand]
        rng = np.random.default_rng(seed)
        hold = rng.random(len(X)) < 0.2
        params = dict(
            objective="regression", learning_rate=0.05, num_leaves=63,
            min_data_in_leaf=max(5, len(X) // 500), feature_fraction=0.9, bagging_fraction=0.8,
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
        active = y_te > 0
        pred = self.booster.predict(X_te)
        base = X_te["users_pm"].to_numpy()
        vn = (venues.loc[cand, "cc"] == "VN").to_numpy()
        metrics = {
            "spearman": spearman(pred[active], y_te[active]),
            "spearman_baseline": spearman(base[active], y_te[active]),
            "spearman_all": spearman(pred, y_te),
            "spearman_all_baseline": spearman(base, y_te),
            "spearman_vn": spearman(pred[vn], y_te[vn]),
            "spearman_vn_baseline": spearman(base[vn], y_te[vn]),
            "n_train": int((~hold).sum()),
            "best_iteration": int(self.booster.best_iteration or 0),
        }
        return metrics

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


def hour_window(p: np.ndarray, mass: float = 0.9) -> tuple[int, int]:
    """Shortest circular run of whole hours holding `mass` of the profile."""
    p = p / p.sum()
    ext = np.concatenate([p, p])
    for length in range(1, HOURS + 1):
        sums = np.array([ext[s : s + length].sum() for s in range(HOURS)])
        s = int(sums.argmax())
        if sums[s] >= mass - 1e-9:
            return s * 60, (s + length) * 60
    return 0, HOURS * 60


def golden_window(p: np.ndarray, minutes: int = 120) -> tuple[int, int]:
    h = minutes // 60
    ext = np.concatenate([p, p])
    sums = np.array([ext[s : s + h].sum() for s in range(HOURS)])
    s = int(sums.argmax())
    return s * 60, s * 60 + minutes


@dataclass
class M2HourProfile:
    kappa_venue: float = 10.0
    kappa_city: float = 20.0
    kappa_cat: float = 20.0
    width: float = 1.0
    global_p: np.ndarray | None = None
    cat_p: dict | None = None
    city_p: dict | None = None

    @staticmethod
    def _hist(checkins: pd.DataFrame, venues: pd.DataFrame, mask: pd.Series) -> np.ndarray:
        c = checkins[mask]
        flat = c["venue_idx"].to_numpy().astype(np.int64) * HOURS + c["local"].dt.hour.to_numpy()
        counts = np.bincount(flat, minlength=len(venues) * HOURS)
        return counts.reshape(len(venues), HOURS).astype(np.float32)

    def _fit_priors(self, venues: pd.DataFrame, hist: np.ndarray) -> None:
        tot = hist.sum(0) + 1.0
        self.global_p = tot / tot.sum()
        self.cat_p, self.city_p = {}, {}
        lab = venues["label"].fillna("").to_numpy()
        city = venues["city"].fillna("").to_numpy()
        for c in np.unique(lab):
            h = hist[lab == c].sum(0)
            self.cat_p[c] = (h + self.kappa_cat * self.global_p) / (h.sum() + self.kappa_cat)
        for c, ci in set(zip(lab, city)):
            h = hist[(lab == c) & (city == ci)].sum(0)
            self.city_p[f"{c}|{ci}"] = (h + self.kappa_city * self.cat_p[c]) / (h.sum() + self.kappa_city)

    def parent(self, venues: pd.DataFrame) -> np.ndarray:
        keys = (venues["label"].fillna("") + "|" + venues["city"].fillna("")).to_numpy()
        labs = venues["label"].fillna("").to_numpy()
        out = np.empty((len(venues), HOURS))
        for i, (k, lb) in enumerate(zip(keys, labs)):
            p = self.city_p.get(k)
            if p is None:
                p = self.cat_p.get(lb, self.global_p)
            out[i] = p
        return out

    def posterior(self, venues: pd.DataFrame, hist: np.ndarray, kappa: float | None = None) -> np.ndarray:
        kappa = self.kappa_venue if kappa is None else kappa
        par = self.parent(venues)
        n = hist.sum(1, keepdims=True)
        p = (hist + kappa * par) / (n + kappa)
        p = circular_smooth(p, self.width)
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
        self._fit_priors(venues, h_tr)
        # choose the venue-level concentration on validation log-likelihood
        best = None
        for kappa in (1, 3, 10, 30, 100):
            for width in (0.75, 1.0, 1.5):
                self.width = width
                ll = self.loglik(self.posterior(venues, h_tr, kappa), h_va)
                if best is None or ll > best[0]:
                    best = (ll, kappa, width)
        _, self.kappa_venue, self.width = best
        # refit priors on train+val, evaluate on test
        h_trva = h_tr + h_va
        self._fit_priors(venues, h_trva)
        p_model = self.posterior(venues, h_trva)
        prior = np.stack([self.cat_p.get(lb, self.global_p) for lb in venues["label"].fillna("")])
        return {
            "loglik": self.loglik(p_model, h_te),
            "loglik_baseline": self.loglik(circular_smooth(prior, self.width), h_te),
            "kappa_venue": float(self.kappa_venue),
            "width": float(self.width),
        }

    def profiles(self, venues: pd.DataFrame, checkins: pd.DataFrame, low_confidence: np.ndarray) -> np.ndarray:
        hist = self._hist(checkins, venues, pd.Series(True, index=checkins.index))
        p = self.posterior(venues, hist)
        # low confidence: use the category estimate (spec IV.1)
        par = circular_smooth(self.parent(venues), self.width)
        p[low_confidence] = par[low_confidence] / par[low_confidence].sum(1, keepdims=True)
        return p

    def save(self, d: Path) -> None:
        np.savez(
            d / "m2.npz",
            global_p=self.global_p,
            cat_keys=np.array(list(self.cat_p)), cat_vals=np.array(list(self.cat_p.values())),
            city_keys=np.array(list(self.city_p)), city_vals=np.array(list(self.city_p.values())),
            params=np.array([self.kappa_venue, self.kappa_city, self.kappa_cat, self.width]),
        )

    @classmethod
    def load(cls, d: Path) -> "M2HourProfile":
        z = np.load(d / "m2.npz", allow_pickle=False)
        kv, kc, kcat, w = z["params"]
        m = cls(kv, kc, kcat, w, z["global_p"])
        m.cat_p = dict(zip(z["cat_keys"].tolist(), z["cat_vals"]))
        m.city_p = dict(zip(z["city_keys"].tolist(), z["city_vals"]))
        return m


# --------------------------------------------------------------------------- #
# M3 - visit length (quantile gradient boosting)
# --------------------------------------------------------------------------- #
@dataclass
class M3VisitLength:
    booster: lgb.Booster | None = None
    labels: list[str] | None = None
    cities: list[str] | None = None
    alpha: float = 0.5
    category_median: dict | None = None

    FEATURES = ["label_code", "group_code", "city_code", "hour", "weekend", "log_users"]

    def _frame(self, venues: pd.DataFrame, venue_idx: np.ndarray, hour: np.ndarray, weekend: np.ndarray) -> pd.DataFrame:
        v = venues.iloc[venue_idx]
        return pd.DataFrame(
            {
                "label_code": _codes(v["label"], self.labels),
                "group_code": _codes(v["group"].fillna(""), ["sightseeing", "entertainment", "food", "nightlife", "shopping"]),
                "city_code": _codes(v["city"].fillna(""), self.cities),
                "hour": hour.astype(np.int16),
                "weekend": weekend.astype(np.int8),
                "log_users": np.log1p(v["n_users"].to_numpy()),
            }
        )

    def fit(self, venues: pd.DataFrame, visits: pd.DataFrame, seed: int = 0) -> dict:
        self.labels = sorted(venues["label"].dropna().unique().tolist())
        self.cities = sorted(venues["city"].dropna().unique().tolist())
        cand = venues["group"].notna().to_numpy()
        vis = visits[cand[visits["venue_idx"].to_numpy()]]
        def xy(mask):
            s = vis[mask]
            X = self._frame(venues, s["venue_idx"].to_numpy(), s["local"].dt.hour.to_numpy(), s["local"].dt.dayofweek.ge(5).to_numpy())
            return X, s["dwell"].to_numpy(), s
        X_tr, y_tr, s_tr = xy(vis["split"] == "train")
        X_va, y_va, _ = xy(vis["split"] == "val")
        X_te, y_te, s_te = xy(vis["split"] == "test")
        params = dict(
            objective="quantile", alpha=self.alpha, learning_rate=0.05, num_leaves=31,
            min_data_in_leaf=max(5, len(X_tr) // 1000), seed=seed, verbose=-1,
        )
        cat = ["label_code", "group_code", "city_code"]
        dtr = lgb.Dataset(X_tr, y_tr, categorical_feature=cat, free_raw_data=False)
        valid = [lgb.Dataset(X_va, y_va, categorical_feature=cat, reference=dtr)] if len(X_va) else []
        cbs = [lgb.early_stopping(100, verbose=False)] if valid else []
        self.booster = lgb.train(params, dtr, num_boost_round=1500, valid_sets=valid, callbacks=cbs)
        labels_tr = venues["label"].to_numpy()[s_tr["venue_idx"].to_numpy()]
        self.category_median = pd.Series(y_tr).groupby(labels_tr).median().to_dict()
        labels_te = venues["label"].to_numpy()[s_te["venue_idx"].to_numpy()]
        base = np.array([self.category_median.get(lb, np.median(y_tr)) for lb in labels_te])
        pred = self.booster.predict(X_te) if len(X_te) else np.array([])
        return {
            "pinball": pinball(y_te, pred, self.alpha) if len(y_te) else float("nan"),
            "pinball_baseline": pinball(y_te, base, self.alpha) if len(y_te) else float("nan"),
            "n_train": int(len(X_tr)),
            "best_iteration": int(self.booster.best_iteration or 0),
        }

    def predict_venues(self, venues: pd.DataFrame, golden_hour: np.ndarray) -> np.ndarray:
        idx = np.arange(len(venues))
        X = self._frame(venues, idx, golden_hour, np.zeros(len(venues)))
        return self.booster.predict(X)

    def save(self, d: Path) -> None:
        self.booster.save_model(str(d / "m3.txt"))
        (d / "m3.json").write_text(
            json.dumps({"labels": self.labels, "cities": self.cities, "alpha": self.alpha, "category_median": self.category_median})
        )

    @classmethod
    def load(cls, d: Path) -> "M3VisitLength":
        meta = json.loads((d / "m3.json").read_text())
        return cls(lgb.Booster(model_file=str(d / "m3.txt")), meta["labels"], meta["cities"], meta["alpha"], meta["category_median"])


def fallback_duration(group: str | None) -> float:
    return float(GROUP_PRIORS.get(group or "", GROUP_PRIORS["sightseeing"])["duration"])
