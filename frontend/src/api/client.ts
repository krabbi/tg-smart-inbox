/**
 * client.ts — base HTTP fetch wrapper for the Foldkit API layer.
 *
 * All API functions return Command<Msg> values — pure data structures describing
 * a side effect that the runtime will execute by calling `run(dispatch)`.
 * No raw Promises leak into view or update code.
 */

// ---------------------------------------------------------------------------
// Command type (Foldkit deferred side-effect primitive)
// ---------------------------------------------------------------------------

/** Represents a deferred side effect. Call run(dispatch) to execute it. */
export type Command<Msg> = {
  run: (dispatch: (msg: Msg) => void) => void;
};

// ---------------------------------------------------------------------------
// Base URL — configurable via Vite env var, falls back to /api for prod proxy
// ---------------------------------------------------------------------------

/**
 * Base URL for all API requests.
 * Set VITE_API_BASE_URL=http://localhost:8000 in .env.local for local dev.
 * In production the nginx proxy forwards /api/ so the default "" works.
 */
const API_BASE: string = import.meta.env["VITE_API_BASE_URL"] ?? "";

// ---------------------------------------------------------------------------
// JWT helpers
// ---------------------------------------------------------------------------

const JWT_STORAGE_KEY = "tg_jwt";

/** Read the JWT from localStorage. Returns null when absent. */
export function getJwt(): string | null {
  return localStorage.getItem(JWT_STORAGE_KEY);
}

/** Persist a JWT to localStorage. */
export function setJwt(token: string): void {
  localStorage.setItem(JWT_STORAGE_KEY, token);
}

/** Remove the JWT from localStorage (on session expiry or explicit logout). */
export function clearJwt(): void {
  localStorage.removeItem(JWT_STORAGE_KEY);
}

// ---------------------------------------------------------------------------
// Request options
// ---------------------------------------------------------------------------

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** When true, do NOT attach an Authorization header (used for login). */
  anonymous?: boolean;
}

// ---------------------------------------------------------------------------
// HTTP error messages the dispatch layer understands
// ---------------------------------------------------------------------------

/** Canonical message type emitted by the HTTP layer on auth failures or HTTP errors. */
export type HttpErrorMsg =
  | { type: "SessionExpired" }
  | { type: "AccessDenied" }
  | { type: "HttpError"; status: number };

// ---------------------------------------------------------------------------
// Core fetch wrapper
// ---------------------------------------------------------------------------

/**
 * Build a Command that fetches `path` and dispatches one of:
 *   - onSuccess(data)  when the response is 2xx
 *   - onError(msg)     when the response is 4xx/5xx or network failure
 *
 * On 401: clears the stored JWT and dispatches { type: "SessionExpired" }.
 * On 403: dispatches { type: "AccessDenied" }.
 *
 * @param path    Path relative to API_BASE (e.g. "/api/items")
 * @param opts    Method, body, anonymous flag
 * @param onSuccess  Called with the parsed JSON body on 2xx (null for 204)
 * @param onError    Called with an error Msg on failure
 */
export function apiRequest<Msg, T>(
  path: string,
  opts: RequestOptions,
  onSuccess: (data: T) => Msg,
  onError: (err: HttpErrorMsg) => Msg,
): Command<Msg> {
  return {
    run(dispatch) {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };

      if (!opts.anonymous) {
        const token = getJwt();
        if (token !== null) {
          headers["Authorization"] = `Bearer ${token}`;
        }
      }

      const init: RequestInit = {
        method: opts.method ?? "GET",
        headers,
      };

      if (opts.body !== undefined) {
        init.body = JSON.stringify(opts.body);
      }

      fetch(`${API_BASE}${path}`, init)
        .then((response) => {
          if (response.status === 401) {
            clearJwt();
            dispatch(onError({ type: "SessionExpired" }));
            return;
          }

          if (response.status === 403) {
            dispatch(onError({ type: "AccessDenied" }));
            return;
          }

          if (!response.ok) {
            // Other non-2xx errors — dispatch HttpError with the actual status code
            // so callers can distinguish 404, 422, 500, etc. from auth failures.
            dispatch(onError({ type: "HttpError", status: response.status }));
            return;
          }

          // 204 No Content — no body to parse.
          if (response.status === 204) {
            dispatch(onSuccess(null as T));
            return;
          }

          response
            .json()
            .then((data: T) => {
              dispatch(onSuccess(data));
            })
            .catch(() => {
              dispatch(onError({ type: "AccessDenied" }));
            });
        })
        .catch(() => {
          // Network error — dispatch SessionExpired so the UI can show re-login.
          dispatch(onError({ type: "SessionExpired" }));
        });
    },
  };
}
