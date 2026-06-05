/**
 * Reminders.ts — Reminders tab content view.
 *
 * Rendered when currentRoute === "reminders".
 * Displays a list of upcoming reminders, each with:
 *   - Item preview text
 *   - remind_at time formatted in the user's timezone (from model.settings.timezone)
 *   - Three action buttons: Acknowledge | Snooze (with <select>) | Cancel
 *
 * After any action the reminder is removed immediately (optimistic update).
 * Empty state: "No upcoming reminders."
 * Loading state: "Loading reminders…"
 */

import type { Model } from "../Model.ts";
import type { Msg } from "../Messages.ts";
import type { ReminderResponse } from "../api/types.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Escape HTML special characters in user-sourced strings. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Format an ISO date-time string into a human-readable date+time string,
 * using the user's configured timezone when available.
 * Falls back to the browser's local timezone when settings are not yet loaded.
 */
function formatRemindAt(iso: string, timezone: string | undefined): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timezone,
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    // Fallback: plain locale string without timezone override.
    try {
      return new Date(iso).toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  }
}

// ---------------------------------------------------------------------------
// Sub-views
// ---------------------------------------------------------------------------

function viewLoadingState(): string {
  return `<div class="list-loading">Loading reminders&hellip;</div>`;
}

function viewEmptyState(): string {
  return `<p class="list-empty-state">No upcoming reminders.</p>`;
}

function viewSnoozeSelect(reminderId: string): string {
  return `
    <select
      class="snooze-select"
      data-action="snooze-select"
      data-id="${escapeHtml(reminderId)}"
      aria-label="Snooze duration"
    >
      <option value="+1h">+1 hour</option>
      <option value="+24h">+24 hours</option>
      <option value="next_day">Next day</option>
    </select>
  `.trim();
}

function viewReminderCard(reminder: ReminderResponse, timezone: string | undefined): string {
  const preview = escapeHtml(reminder.item_preview);
  const remindAt = escapeHtml(formatRemindAt(reminder.remind_at, timezone));
  const id = escapeHtml(reminder.id);

  return `
    <div class="reminder-card" data-id="${id}">
      <div class="reminder-card-body">
        <p class="reminder-preview">${preview}</p>
        <span class="reminder-time">${remindAt}</span>
      </div>
      <div class="reminder-card-actions">
        <button
          class="btn btn-primary reminder-ack"
          data-action="ack-reminder"
          data-id="${id}"
        >Acknowledge</button>
        <div class="snooze-group">
          ${viewSnoozeSelect(reminder.id)}
          <button
            class="btn btn-secondary reminder-snooze"
            data-action="snooze-reminder"
            data-id="${id}"
          >Snooze &#9660;</button>
        </div>
        <button
          class="btn btn-danger reminder-cancel"
          data-action="cancel-reminder"
          data-id="${id}"
        >Cancel</button>
      </div>
    </div>
  `.trim();
}

// ---------------------------------------------------------------------------
// Public view
// ---------------------------------------------------------------------------

/**
 * Render the full reminders panel.
 * Pure function — takes the Model and returns an HTML string.
 */
export function view(model: Model): string {
  const { reminders } = model;
  const timezone = model.settings?.timezone;

  let contentHtml: string;
  if (reminders.isLoading) {
    contentHtml = viewLoadingState();
  } else if (reminders.error !== null) {
    contentHtml = `<p class="list-empty-state">Failed to load reminders.</p>`;
  } else if (reminders.reminders.length === 0) {
    contentHtml = viewEmptyState();
  } else {
    const cardsHtml = reminders.reminders
      .map((r) => viewReminderCard(r, timezone))
      .join("\n");
    contentHtml = `<div class="reminders-list">${cardsHtml}</div>`;
  }

  return `
    <div class="reminders-view">
      ${contentHtml}
    </div>
  `.trim();
}

// ---------------------------------------------------------------------------
// Listener wiring
// ---------------------------------------------------------------------------

/**
 * Attach DOM event listeners for the reminders panel.
 * Must be called every time the reminders view is rendered into the DOM.
 */
export function attachRemindersListeners(
  root: HTMLElement,
  dispatch: (msg: Msg) => void,
): void {
  // Acknowledge button
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='ack-reminder']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset["id"];
        if (id !== undefined) {
          dispatch({ type: "AckReminder", id });
        }
      });
    });

  // Cancel button
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='cancel-reminder']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset["id"];
        if (id !== undefined) {
          dispatch({ type: "CancelReminder", id });
        }
      });
    });

  // Snooze button — reads the selected option from the sibling <select>
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='snooze-reminder']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset["id"];
        if (id === undefined) return;

        // The <select> is a sibling inside the same .snooze-group container.
        const snoozeGroup = btn.closest(".snooze-group");
        const select = snoozeGroup?.querySelector<HTMLSelectElement>(
          "select[data-action='snooze-select']",
        );
        const optionValue = select?.value as "+1h" | "+24h" | "next_day" | undefined;
        if (optionValue === undefined) return;

        dispatch({ type: "SnoozeReminder", id, option: optionValue });
      });
    });
}
