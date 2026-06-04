/**
 * Messages.ts — Union of all Msg values the application can receive.
 *
 * Follows the Elm Architecture pattern: every event (user action, HTTP
 * response, timer tick) is represented as a plain data value of type Msg.
 * update() in Main.ts pattern-matches on Msg to produce the next Model.
 */

import type { TelegramLoginPayload, MeResponse, ItemListResponse, ItemDetail } from "./api/types.ts";
import type { HttpErrorMsg } from "./api/client.ts";
import type { Route } from "./Model.ts";

// ---------------------------------------------------------------------------
// Msg union
// ---------------------------------------------------------------------------

export type Msg =
  // --- Auth messages -------------------------------------------------------

  /** User completed the Telegram Login Widget flow; raw payload ready to POST. */
  | { type: "TelegramLoginSuccess"; payload: TelegramLoginPayload }

  /** POST /api/auth/telegram succeeded; JWT and user info are now available. */
  | { type: "AuthSuccess"; token: string; user: MeResponse }

  /** Authentication attempt failed (wrong hash, server error, etc.). */
  | { type: "AuthFailed"; reason: string }

  /**
   * The stored JWT was rejected by the server (401 on any authenticated
   * request). Clears localStorage and returns to the login view.
   */
  | { type: "SessionExpired" }

  /** Server returned 403 — user is authenticated but not whitelisted. */
  | { type: "AccessDenied" }

  /**
   * GET /api/auth/me succeeded on startup — the stored JWT is still valid.
   * Carries the user identity so the Model can be populated.
   */
  | { type: "MeLoaded"; user: MeResponse }

  // --- Navigation messages -------------------------------------------------

  /** User clicked a sidebar tab; app should switch to the given route. */
  | { type: "NavigateTo"; route: Route }

  // --- Global UI messages --------------------------------------------------

  /** Dismiss the current error banner. */
  | { type: "ClearError" }

  // --- Item list messages --------------------------------------------------

  /** GET /api/items succeeded; carries the full paginated response. */
  | { type: "ItemsLoaded"; data: ItemListResponse }

  /** GET /api/items/{id} succeeded; carries the full item detail. */
  | { type: "ItemLoaded"; data: ItemDetail }

  /** An item API call failed. */
  | { type: "ItemsError"; err: HttpErrorMsg }

  /** User clicked an item card; opens the detail panel. */
  | { type: "SelectItem"; id: string }

  /** User clicked Back in the detail panel; returns to the list. */
  | { type: "BackToList" }

  /** User submitted a search query. */
  | { type: "SearchItems"; q: string }

  /** User cleared the search bar; returns to the unfiltered list. */
  | { type: "ClearSearch" }

  /** User clicked prev/next pagination button. */
  | { type: "ChangePage"; page: number }

  /** User toggled a checkbox on an item card. */
  | { type: "ToggleItemCheck"; id: string }

  /** User clicked the delete button on a single item card. */
  | { type: "RequestDeleteItem"; id: string }

  /** User confirmed the single-item delete dialog. */
  | { type: "ConfirmDeleteItem" }

  /** User cancelled any delete confirmation dialog. */
  | { type: "CancelDelete" }

  /** Single DELETE /api/items/{id} succeeded. */
  | { type: "ItemDeleted"; id: string }

  /** User clicked "Delete selected (N)" bulk delete button. */
  | { type: "RequestBulkDelete" }

  /** User confirmed the bulk-delete dialog. */
  | { type: "ConfirmBulkDelete" }

  /** Bulk DELETE /api/items succeeded; carries count of deleted items. */
  | { type: "ItemsBulkDeleted"; deleted: number }

  /** Dismiss the post-bulk-delete feedback message. */
  | { type: "ClearItemFeedback" };
