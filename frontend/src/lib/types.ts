// Field names match backend/app/schemas.py
export type Confidence = "high" | "medium" | "low";
export type Group = "sightseeing" | "entertainment" | "food" | "nightlife" | "shopping";
export type Interest = "food" | "culture" | "nature" | "nightlife" | "shopping";
export type HoursSource = "crawl" | "estimated";
export type PlaceQuality = "good" | "low_data" | "missing_hours";

export interface Place {
  id: number;
  city: string;
  ward: string;
  lat: number;
  lon: number;
  category: string;
  label: string;
  group: Group;
  effort: number;
  score: number;
  duration: number;
  open_min: number;
  close_min: number;
  golden_start: number;
  golden_end: number;
  confidence: Confidence;
  n_checkins: number;
  estimated: boolean;
  // optional: trips saved before these fields existed do not have them
  duration_lo?: number;
  duration_hi?: number;
  hours_source?: HoursSource;
  closed_days?: number[]; // 0 = Monday (Python weekday), not JS getDay()
  conf_m1?: Confidence;
  conf_m2?: Confidence;
  conf_m3?: Confidence;
  venue?: string;
  interest?: Interest;
}

export interface PlaceDetail extends Place {
  hour_profile: number[];
  n_users: number;
  n_visits: number;
  one_time_share: number;
  visit_hist: number[];
  model_versions: Record<string, string>;
  quality: PlaceQuality;
}

export interface City {
  name: string;
  lat: number;
  lon: number;
  stay: { lat: number; lon: number; label: string };
  places: number;
}

export interface Point {
  lat: number;
  lon: number;
  label: string;
}

export interface Preferences {
  pace: number;
  travel: number;
  strictness: number;
}

export interface Lock {
  place_id: number;
  day: number;
  start: number | null;
}

export interface OptimizeRequest {
  city: string;
  place_ids: number[];
  days: number;
  start_date?: string | null; // YYYY-MM-DD
  day_start: number;
  day_end: number;
  stay: Point;
  preferences: Preferences;
  locks: Lock[];
  seed_plan?: number[][] | null;
  must_visit?: number[];
}

export interface Stop {
  place: Place;
  arrive: number;
  start: number;
  depart: number;
  wait: number;
  travel_in: number;
  golden: boolean;
  meal_break_before: number;
  locked: boolean;
  locked_start: number | null;
  late_by: number;
}

export interface Day {
  day: number;
  start: number;
  return_time: number;
  return_travel: number;
  meal_break_before_return: number;
  travel_minutes: number;
  wait_minutes: number;
  stops: Stop[];
  warnings: string[];
}

export interface PlanFix {
  kind: "add_day" | "extend_day" | "move_place" | "drop_places";
  label: string;
  patch: Partial<OptimizeRequest>;
  fits: boolean;
  recommended: boolean;
}

export interface PlanFit {
  missing: number[];
  day: number | null;
  needed_min: number;
  available_min: number;
  fixes: PlanFix[];
}

export interface Itinerary {
  days: Day[];
  unscheduled: Place[];
  fitness: number;
  generations: number;
  runtime_s: number;
  travel_source: "osrm" | "estimate";
  weights: Record<string, number>;
  warnings?: string[];
  plan_fit?: PlanFit | null;
}

export interface OptimizeJob {
  id: string;
  status: "running" | "done" | "failed" | "cancelled";
  generation: number;
  max_generations: number;
  best_stops: number;
  best_travel_min: number;
  steps: { key: string; label: string; done: boolean }[];
  result: Itinerary | null;
  error: string | null;
}

// ---- Saved trips (T4) ----
export type TripStatus = "draft" | "upcoming" | "past";

export interface DayOverview {
  day: number;
  date: string | null;
  stops: number;
  travel_minutes: number;
  first_stop: number | null;
  back_at: number;
}

export interface Trip {
  id: number;
  title: string;
  city: string;
  start_date: string | null;
  end_date: string | null;
  days: number;
  status: TripStatus;
  stops: number;
  request: OptimizeRequest;
  itinerary: Itinerary | null;
  overview: DayOverview[];
  share_enabled: boolean;
  share_slug: string | null;
  improve_estimates: boolean;
  stale_places: number[];
  created_at: string;
  updated_at: string;
}

export interface TripCreated extends Trip {
  edit_token: string;
}

export interface SharedTrip {
  title: string;
  city: string;
  start_date: string | null;
  end_date: string | null;
  days: number;
  itinerary: Itinerary | null;
  overview: DayOverview[];
}

export interface EditEvent {
  kind: "move" | "remove" | "add" | "lock" | "unlock" | "set_duration" | "reoptimize";
  place_id?: number;
  day?: number;
  value?: number;
}

// ---- Admin (legacy overview, still used for the dataset download) ----
export interface CountryStat {
  country: string;
  checkins: number;
  users: number;
  venues: number;
  source: string;
}

export type ModelState = "queued" | "training" | "trained" | "failed";

export interface ModelVersion {
  version: string;
  source: string;
  created_at: string;
  metrics: Record<string, unknown>;
  places: number;
  is_active: boolean;
}

export interface Job {
  id: number;
  source: string;
  status: "queued" | "running" | "done" | "failed";
  models: Record<string, ModelState>;
  message: string;
  version: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface AdminOverview {
  country_stats: CountryStat[];
  versions: ModelVersion[];
  job: Job | null;
  dataset_found: boolean;
  raw_dir: string;
}

export interface DatasetStatus {
  found: boolean;
  raw_dir: string;
  running: boolean;
  progress: { stage?: string; file?: string; done?: number; total?: number; speed?: number; eta?: number } | null;
  error: string | null;
}

// ---- Data console (D1-D4) ----
export interface DataOverview {
  checkins: number;
  checkins_period: string;
  places: number;
  cities: { name: string; places: number; ready: boolean }[];
  last_run: string | null;
  last_run_minutes: number | null;
  dataset_version: string | null;
  sources: {
    key: string;
    name: string;
    provides: string;
    rows: number | null;
    updated: string | null;
    status: "imported" | "synced" | "missing" | "outdated" | "online" | "estimate";
  }[];
  pipeline: { key: string; label: string; value: string }[];
  issues: {
    key: string;
    impact: "high" | "medium" | "low";
    title: string;
    detail: string;
    action: "crawl_hours" | "retrain" | "review_places" | null;
  }[];
}

export interface CrawlStatus {
  running: boolean;
  places: number | null;
  usable: number | null;
  updated: string | null;
  error: string | null;
}

export interface ExplorerPage {
  city: string;
  total: number;
  places: { id: number; venue: string; name: string; group: string; n_checkins: number; quality: PlaceQuality }[];
}

export type ModelKey = "m1" | "m2" | "m3";

export interface Headline {
  name: string;
  value: number | null;
  baseline: number | null;
  unit: string;
  higher_is_better: boolean;
}

export interface ModelCard {
  key: ModelKey;
  name: string;
  description: string;
  active_version: string | null;
  status: "active" | "training" | "new_run_ready" | "failed" | "untrained";
  progress: number | null;
  latest: string | null;
  settings: Record<string, number>;
  split: { kind: string; train_end?: string | null; val_end?: string | null; shares: Record<string, number> };
}

export interface M3Metrics {
  mae?: number | null;
  rmse?: number | null;
  within_15?: number | null;
  mae_baseline?: number | null;
  rmse_baseline?: number | null;
  within_15_baseline?: number | null;
  best_iteration?: number;
  learning_curve?: { iteration: number[]; train: number[]; valid?: number[] };
  largest_errors?: { place: string; city: string; error_min: number; actual_min: number; predicted_min: number; n_visits: number }[];
  [key: string]: unknown;
}

export interface ModelVersionRow {
  version: string;
  created_at: string;
  source: string;
  trained: boolean;
  origin: string;
  active: boolean;
  headline: Headline;
  metrics: M3Metrics;
  settings: Record<string, number>;
}

export interface ModelDetail extends ModelCard {
  versions: ModelVersionRow[];
}

export interface Impact {
  model: ModelKey;
  version: string;
  against: string;
  places_compared: number;
  places_changed: number;
  mean_change: number;
  unit: string;
  trips_affected: number;
  message: string;
}

export interface OptimizerSettings {
  population: number;
  generations: number;
  crossover: number;
  mutation: number;
  time_limit_s: number;
  local_search: boolean;
  objective: { popularity: number; golden: number; travel: number };
}

export interface Benchmark {
  id: number;
  status: "running" | "done" | "failed";
  settings: OptimizerSettings;
  active: OptimizerSettings;
  score_change: number | null;
  violations: number | null;
  median_runtime_s: number | null;
  curve: { generation: number[]; active: number[]; new: number[] } | null;
  cases: { name: string; city: string; places: number; days: number; score_active: number; score_new: number; violations: number; runtime_s: number }[];
  ready_to_apply: boolean;
  error: string | null;
  created_at: string;
}

export interface OptimizerOut {
  active: OptimizerSettings;
  updated_at: string | null;
  last_benchmark: Benchmark | null;
}
