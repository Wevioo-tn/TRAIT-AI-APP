import type {
  ApiErrorBody,
  DecisionRead,
  Face,
  LoginResponse,
  TraiteCountsRead,
  TraiteCreate,
  TraiteDetail,
  TraitePage,
  TraiteRead,
  TraiteStatusRead,
  VerificationCode,
  StatutVerification,
  TypeDecision,
} from "./types";

// Reachable from the browser, not from inside the Docker network — hence
// localhost rather than the "backend" service name (see docker-compose.yml).
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// Every route except /auth/login requires this Bearer token (see
// app/api/routes/traites.py's router-level dependency). AuthContext keeps
// this in sync on login/logout, but the *initial* value is read here,
// synchronously at module load — not from a useEffect in AuthContext.
// React runs a child's effects before its parent's, so on a full page
// reload QueuePage's data-fetching effects would otherwise fire (and get
// a real 401) before AuthProvider's effect had set the token.
export const AUTH_STORAGE_KEY = "trait-ai-auth";

function readPersistedToken(): string | null {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    return (JSON.parse(raw) as { token: string }).token ?? null;
  } catch {
    return null;
  }
}

let authToken: string | null = readPersistedToken();
export function setAuthToken(token: string | null): void {
  authToken = token;
}

// Lets AuthContext force a logout when any call comes back 401 — e.g. the
// token expired mid-session, not just at page load.
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.();
    let detail = `Erreur HTTP ${response.status}`;
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (body.detail) detail = body.detail;
    } catch {
      // Non-JSON error body — keep the generic message.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function login(username: string, password: string) {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

/** Fetches a document's bytes as a Blob, with the same Bearer token as
 * every other call — a plain <img src>/<a href> URL can't carry an
 * Authorization header, so callers must turn this into an object URL
 * (see AnalysisPage's DocumentViewer). */
export async function getDocumentBlob(traiteId: string, face: Face): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/traites/${traiteId}/documents/${face}`, {
    headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
  });
  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.();
    throw new ApiError(response.status, `Erreur HTTP ${response.status}`);
  }
  return response.blob();
}

export function listTraites(params: { statut?: string; page?: number; per_page?: number } = {}) {
  const query = new URLSearchParams();
  if (params.statut) query.set("statut", params.statut);
  if (params.page) query.set("page", String(params.page));
  if (params.per_page) query.set("per_page", String(params.per_page));
  const qs = query.toString();
  return request<TraitePage>(`/traites${qs ? `?${qs}` : ""}`);
}

export function getTraiteCounts() {
  return request<TraiteCountsRead>("/traites/counts");
}

export function getTraite(id: string) {
  return request<TraiteDetail>(`/traites/${id}`);
}

export function getTraiteStatus(id: string) {
  return request<TraiteStatusRead>(`/traites/${id}/status`);
}

export function createTraite(payload: TraiteCreate) {
  return request<TraiteDetail>("/traites", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function uploadDocument(traiteId: string, face: Face, file: File, replace = false) {
  const form = new FormData();
  form.set("file", file);
  const query = new URLSearchParams({ face, ...(replace ? { replace: "true" } : {}) });
  return request<TraiteRead>(`/traites/${traiteId}/documents?${query.toString()}`, {
    method: "POST",
    body: form,
  });
}

export function lancerAnalyse(traiteId: string) {
  return request<TraiteRead>(`/traites/${traiteId}/analyse`, { method: "POST" });
}

export function updateVerification(traiteId: string, code: VerificationCode, statut: StatutVerification | null) {
  return request<TraiteDetail>(`/traites/${traiteId}/verifications/${code}`, {
    method: "PATCH",
    body: JSON.stringify({ statut }),
  });
}

export function createDecision(traiteId: string, type: TypeDecision, commentaire?: string) {
  return request<DecisionRead>(`/traites/${traiteId}/decisions`, {
    method: "POST",
    body: JSON.stringify({ type, commentaire }),
  });
}
