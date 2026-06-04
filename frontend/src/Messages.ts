/**
 * Messages.ts — Union of all Msg values the application can receive.
 *
 * Follows the Elm Architecture pattern: every event (user action, HTTP
 * response, timer tick) is represented as a plain data value of type Msg.
 * update() in Main.ts pattern-matches on Msg to produce the next Model.
 *
 * Child view messages (ItemList, Reminders, Login) will be added in
 * subsequent tasks (#188, #189, #190) as their own Msg subtypes and wired
 * into this union.
 */

import type { TelegramLoginPayload, MeResponse } from "./api/types.ts";
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
  | { type: "ClearError" };
