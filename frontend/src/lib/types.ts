export type Confidence = "high" | "medium" | "low";
export type Group = "sightseeing" | "entertainment" | "food" | "nightlife" | "shopping";

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
}

export interface PlaceDetail extends Place {
  hour_profile: number[];
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
  day_start: number;
  day_end: number;
  stay: Point;
  preferences: Preferences;
  locks: Lock[];
  seed_plan?: number[][] | null;
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

export interface Itinerary {
  days: Day[];
  unscheduled: Place[];
  fitness: number;
  generations: number;
  runtime_s: number;
  travel_source: "osrm" | "estimate";
  weights: Record<string, number>;
}

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
  metrics: Record<string, Record<string, number | null>>;
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
