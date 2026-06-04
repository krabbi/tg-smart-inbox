/**
 * reminders.ts — API commands for reminder endpoints.
 *
 * GET   /api/reminders        — list upcoming reminders
 * PATCH /api/reminders/{id}   — acknowledge, cancel, or snooze a reminder
 */

import { apiRequest, type Command, type HttpErrorMsg } from "./client.ts";
import type { ReminderAction, ReminderResponse } from "./types.ts";

// ---------------------------------------------------------------------------
// Message types produced by reminder commands
// ---------------------------------------------------------------------------

export type RemindersMsg =
  | { type: "RemindersLoaded"; reminders: ReminderResponse[] }
  | { type: "ReminderUpdated"; reminder: ReminderResponse }
  | { type: "RemindersError"; err: HttpErrorMsg };

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

/**
 * Return a Command that GETs /api/reminders and dispatches RemindersLoaded on
 * success or RemindersError on failure.
 */
export function getReminders(): Command<RemindersMsg> {
  return apiRequest<RemindersMsg, ReminderResponse[]>(
    "/api/reminders",
    { method: "GET" },
    (data) => ({ type: "RemindersLoaded", reminders: data }),
    (err) => ({ type: "RemindersError", err }),
  );
}

/**
 * Return a Command that PATCHes /api/reminders/{id} with the given action and
 * dispatches ReminderUpdated on success or RemindersError on failure.
 */
export function patchReminder(
  id: string,
  action: ReminderAction,
): Command<RemindersMsg> {
  return apiRequest<RemindersMsg, ReminderResponse>(
    `/api/reminders/${encodeURIComponent(id)}`,
    { method: "PATCH", body: action },
    (data) => ({ type: "ReminderUpdated", reminder: data }),
    (err) => ({ type: "RemindersError", err }),
  );
}
