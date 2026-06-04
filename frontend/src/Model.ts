/**
 * Model.ts — Application state for the Foldkit SPA.
 *
 * Follows the Elm Architecture: a single immutable Model describes the entire
 * app state. update() produces a new Model from the current one and a Msg.
 */

import type { MeResponse, ItemSummary, ItemDetail } from "./api/types.ts";

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
// DeleteConfirmState — tracks which delete dialog is open
// ---------------------------------------------------------------------------

/**
 * Discriminated union describing the state of any pending delete confirmation.
 *
 *   none        — no dialog is open
 *   single      — user clicked delete on one item; id is the candidate
 *   bulk        — user clicked "Delete selected (N)"; ids are the candidates
 */
export type DeleteConfirmState =
  | { tag: "none" }
  | { tag: "single"; id: string }
  | { tag: "bulk"; ids: string[] };

// ---------------------------------------------------------------------------
// ItemListState — state for the item list / detail content area
// ---------------------------------------------------------------------------

/** State for the item browsing content area. */
export interface ItemListState {
  /** Items currently shown in the list (current page). */
  items: ItemSummary[];
  /** Current page number (1-based). */
  page: number;
  /** Total number of pages available. */
  total_pages: number;
  /** True while an item list fetch is in flight. */
  isLoading: boolean;
  /** Active search query; empty string means no search is active. */
  searchQuery: string;
  /** ID of the item whose detail panel is open; null when showing the list. */
  selectedItemId: string | null;
  /** IDs of items whose checkboxes are checked. */
  checkedIds: Set<string>;
  /** State of any pending delete confirmation dialog. */
  deleteConfirm: DeleteConfirmState;
  /** Full item detail loaded via GET /api/items/{id}; null when not yet loaded. */
  loadedDetail: ItemDetail | null;
  /** Transient feedback message shown after bulk delete (e.g. "Deleted 3 items"). */
  feedback: string | null;
}

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
  /** State for the item list and detail content area. */
  itemList: ItemListState;
}

// ---------------------------------------------------------------------------
// Initial model
// ---------------------------------------------------------------------------

const initialItemListState: ItemListState = {
  items: [],
  page: 1,
  total_pages: 1,
  isLoading: false,
  searchQuery: "",
  selectedItemId: null,
  checkedIds: new Set(),
  deleteConfirm: { tag: "none" },
  loadedDetail: null,
  feedback: null,
};

/** Starting state before init has run. */
export const initialModel: Model = {
  auth: { tag: "unauthenticated" },
  currentRoute: "all",
  isLoading: false,
  error: null,
  itemList: initialItemListState,
};

/** Produce a fresh ItemListState, preserving the current search query if desired. */
export function resetItemListState(preserveSearch = false, current?: ItemListState): ItemListState {
  return {
    ...initialItemListState,
    searchQuery: preserveSearch && current ? current.searchQuery : "",
  };
}
