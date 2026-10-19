import type {
  AdminOverview,
  City,
  DatasetStatus,
  Itinerary,
  Job,
  ModelVersion,
  OptimizeRequest,
  Place,
  PlaceDetail,
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

async function request<T>(path: string, init: RequestInit & { admin?: boolean } = {}): Promise<T> {
  const headers = new Headers(init.headers);
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
  return res.json() as Promise<T>;
}

const q = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  ).toString();

export const api = {
  cities: () => request<City[]>("/api/cities"),
  places: (city: string, opts: { bbox?: string; limit?: number } = {}) =>
    request<Place[]>(`/api/places?${q({ city, ...opts })}`),
  suggest: (city: string, limit = 8) => request<Place[]>(`/api/places/suggest?${q({ city, limit })}`),
  place: (id: number) => request<PlaceDetail>(`/api/places/${id}`),
  optimize: (body: OptimizeRequest, signal?: AbortSignal) =>
    request<Itinerary>("/api/itinerary/optimize", { method: "POST", body: JSON.stringify(body), signal }),

  overview: () => request<AdminOverview>("/api/admin/overview", { admin: true }),
  train: (source: "auto" | "dataset" | "sample" = "auto") =>
    request<Job>("/api/admin/train", { method: "POST", body: JSON.stringify({ source }), admin: true }),
  job: (id: number) => request<Job>(`/api/admin/jobs/${id}`, { admin: true }),
  activate: (version: string) =>
    request<ModelVersion>(`/api/admin/versions/${encodeURIComponent(version)}/activate`, { method: "POST", admin: true }),
  dataset: () => request<DatasetStatus>("/api/admin/dataset", { admin: true }),
  downloadDataset: () => request<DatasetStatus>("/api/admin/dataset/download", { method: "POST", admin: true }),
};
