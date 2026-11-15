import type {
  AdminOverview,
  Benchmark,
  City,
  CrawlStatus,
  DataOverview,
  DatasetStatus,
  EditEvent,
  ExplorerPage,
  Impact,
  Interest,
  Itinerary,
  Job,
  ModelCard,
  ModelDetail,
  ModelKey,
  ModelVersion,
  OptimizeJob,
  OptimizeRequest,
  OptimizerOut,
  OptimizerSettings,
  Place,
  PlaceDetail,
  PlaceQuality,
  SharedTrip,
  Trip,
  TripCreated,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const ADMIN_TOKEN_KEY = "chronotrip.adminToken";

export function getAdminToken(): string {
  try {
    return sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string) {
  try {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
  } catch {
    /* private mode: token lives only for this request */
  }
}

async function request<T>(path: string, init: RequestInit & { admin?: boolean; trip?: string } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.trip) headers.set("X-Trip-Token", init.trip);
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.admin) {
    const token = getAdminToken();
    if (token) headers.set("X-Admin-Token", token);
  }
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "Can't reach the ChronoTrip server. Is the API running on port 8000?");
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// arrays repeat the key (?interest=food&interest=nature), empty values are dropped
const q = (params: Record<string, string | number | string[] | undefined>) =>
  new URLSearchParams(
    Object.entries(params).flatMap(([k, v]) =>
      v === undefined || v === "" ? [] : Array.isArray(v) ? v.map((x) => [k, x]) : [[k, String(v)]],
    ),
  ).toString();

const json = (method: string, body?: unknown) => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  cities: () => request<City[]>("/api/cities"),
  places: (city: string, opts: { bbox?: string; limit?: number; q?: string; interest?: Interest[] } = {}) =>
    request<Place[]>(`/api/places?${q({ city, ...opts })}`),
  suggest: (city: string, limit = 8, interest?: Interest[]) =>
    request<Place[]>(`/api/places/suggest?${q({ city, limit, interest })}`),
  place: (id: number) => request<PlaceDetail>(`/api/places/${id}`),
  optimize: (body: OptimizeRequest, signal?: AbortSignal) =>
    request<Itinerary>("/api/itinerary/optimize", { ...json("POST", body), signal }),
  startJob: (body: OptimizeRequest) => request<OptimizeJob>("/api/itinerary/jobs", json("POST", body)),
  pollJob: (id: string) => request<OptimizeJob>(`/api/itinerary/jobs/${id}`),
  cancelJob: (id: string) => request<OptimizeJob>(`/api/itinerary/jobs/${id}`, { method: "DELETE" }),

  createTrip: (body: { title?: string; request: OptimizeRequest; itinerary?: Itinerary | null; improve_estimates?: boolean }) =>
    request<TripCreated>("/api/trips", json("POST", body)),
  lookupTrips: (trips: { id: number; token: string }[]) => request<Trip[]>("/api/trips/lookup", json("POST", { trips })),
  updateTrip: (id: number, token: string, body: Partial<Pick<Trip, "title" | "request" | "itinerary" | "improve_estimates">>) =>
    request<Trip>(`/api/trips/${id}`, { ...json("PATCH", body), trip: token }),
  deleteTrip: (id: number, token: string) => request<void>(`/api/trips/${id}`, { method: "DELETE", trip: token }),
  shareTrip: (id: number, token: string, enabled: boolean) =>
    request<Trip>(`/api/trips/${id}/share`, { ...json("PUT", { enabled }), trip: token }),
  sendEdits: (id: number, token: string, events: EditEvent[]) =>
    request<{ stored: number }>(`/api/trips/${id}/edits`, { ...json("POST", { events }), trip: token }),
  shared: (slug: string) => request<SharedTrip>(`/api/shared/${encodeURIComponent(slug)}`),
  /** plain links so the browser downloads the file itself */
  exportUrl: (id: number, token: string, ext: "gpx" | "ics") => `/api/trips/${id}/export.${ext}?${q({ token })}`,
  sharedExportUrl: (slug: string, ext: "gpx" | "ics") => `/api/shared/${encodeURIComponent(slug)}/export.${ext}`,

  overview: () => request<AdminOverview>("/api/admin/overview", { admin: true }),
  train: (source: "auto" | "dataset" | "sample" = "auto") =>
    request<Job>("/api/admin/train", { method: "POST", body: JSON.stringify({ source }), admin: true }),
  job: (id: number) => request<Job>(`/api/admin/jobs/${id}`, { admin: true }),
  activate: (version: string) =>
    request<ModelVersion>(`/api/admin/versions/${encodeURIComponent(version)}/activate`, { method: "POST", admin: true }),
  dataset: () => request<DatasetStatus>("/api/admin/dataset", { admin: true }),
  downloadDataset: () => request<DatasetStatus>("/api/admin/dataset/download", { method: "POST", admin: true }),

  data: () => request<DataOverview>("/api/admin/data", { admin: true }),
  hours: () => request<CrawlStatus>("/api/admin/hours", { admin: true }),
  crawlHours: () => request<CrawlStatus>("/api/admin/hours/crawl", { method: "POST", admin: true }),
  explorer: (opts: { city: string; q?: string; quality?: PlaceQuality; limit?: number; offset?: number }) =>
    request<ExplorerPage>(`/api/admin/places?${q(opts)}`, { admin: true }),
  models: () => request<ModelCard[]>("/api/admin/models", { admin: true }),
  model: (m: ModelKey) => request<ModelDetail>(`/api/admin/models/${m}`, { admin: true }),
  trainModel: (m: ModelKey, settings: Record<string, number>) =>
    request<Job>(`/api/admin/models/${m}/train`, { ...json("POST", { settings }), admin: true }),
  impact: (m: ModelKey, v: string) =>
    request<Impact>(`/api/admin/models/${m}/versions/${encodeURIComponent(v)}/impact`, { admin: true }),
  activateModel: (m: ModelKey, v: string) =>
    request<Job>(`/api/admin/models/${m}/versions/${encodeURIComponent(v)}/activate`, { method: "POST", admin: true }),
  optimizer: () => request<OptimizerOut>("/api/admin/optimizer", { admin: true }),
  benchmark: (settings: OptimizerSettings) =>
    request<Benchmark>("/api/admin/optimizer/benchmark", { ...json("POST", settings), admin: true }),
  pollBenchmark: (id: number) => request<Benchmark>(`/api/admin/optimizer/benchmarks/${id}`, { admin: true }),
  applyOptimizer: (settings: OptimizerSettings) =>
    request<OptimizerOut>("/api/admin/optimizer/apply", { ...json("POST", settings), admin: true }),
};
