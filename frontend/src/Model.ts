/**
 * Model.ts — Application state for the Foldkit SPA.
 *
 * Follows the Elm Architecture: a single immutable Model describes the entire
 * app state. update() produces a new Model from the current one and a Msg.
 */

import type { MeResponse } from "./api/types.ts";

// ---------------------------------------------------------------------------
// UserInfo — the authenticated user's identity (from GET /api/auth/me)
// ---------------------------------------------------------------------------

/** Authenticated user's identity, sourced from JWT claims via /api/auth/me. */
export type UserInfo = MeResponse;

// ---------------------------------------------------------------------------
// AuthState
// ---------------------------------------------------------------------------

/** Discriminated union representing whether the user is authenticated. */
export type AuthState =
  | { tag: "unauthenticated" }
  | { tag: "authenticated"; token: string; user: UserInfo };

// ---------------------------------------------------------------------------
// Route
// ---------------------------------------------------------------------------

/** All top-level navigation routes available in the sidebar. */
export type Route = "all" | "tasks" | "notes" | "links" | "ideas" | "reminders";

/** All valid route values, used for runtime validation. */
export const ALL_ROUTES: Route[] = [
  "all",
  "tasks",
  "notes",
  "links",
  "ideas",
  "reminders",
];

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

/** Complete application state. Immutable — update() returns a new Model. */
export interface Model {
  /** Authentication state — drives which top-level view is shown. */
  auth: AuthState;
  /** Currently active sidebar route. */
  currentRoute: Route;
  /** True while an async operation (e.g. /api/auth/me validation) is in flight. */
  isLoading: boolean;
  /** Non-null when a recoverable error should be shown to the user. */
  error: string | null;
}

// ---------------------------------------------------------------------------
// Initial model
// ---------------------------------------------------------------------------

/** Starting state before init has run. */
export const initialModel: Model = {
  auth: { tag: "unauthenticated" },
  currentRoute: "all",
  isLoading: false,
  error: null,
};
