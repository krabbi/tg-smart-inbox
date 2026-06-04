/**
 * settings.ts — API commands for settings endpoints.
 *
 * GET /api/settings — return the current user's settings
 */

import { apiRequest, type Command, type HttpErrorMsg } from "./client.ts";
import type { PatchSettingsRequest, SettingsResponse } from "./types.ts";

// ---------------------------------------------------------------------------
// Message types produced by settings commands
// ---------------------------------------------------------------------------

export type SettingsMsg =
  | { type: "SettingsLoaded"; settings: SettingsResponse }
  | { type: "SettingsUpdated"; settings: SettingsResponse }
  | { type: "SettingsError"; err: HttpErrorMsg };

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

/**
 * Return a Command that GETs /api/settings and dispatches SettingsLoaded on
 * success or SettingsError on failure.
 */
export function getSettings(): Command<SettingsMsg> {
  return apiRequest<SettingsMsg, SettingsResponse>(
    "/api/settings",
    { method: "GET" },
    (data) => ({ type: "SettingsLoaded", settings: data }),
    (err) => ({ type: "SettingsError", err }),
  );
}

/**
 * Return a Command that PATCHes /api/settings with the given partial update
 * and dispatches SettingsUpdated on success or SettingsError on failure.
 */
export function patchSettings(body: PatchSettingsRequest): Command<SettingsMsg> {
  return apiRequest<SettingsMsg, SettingsResponse>(
    "/api/settings",
    { method: "PATCH", body },
    (data) => ({ type: "SettingsUpdated", settings: data }),
    (err) => ({ type: "SettingsError", err }),
  );
}
