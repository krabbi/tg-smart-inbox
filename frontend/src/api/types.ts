/**
 * types.ts — TypeScript response/request types that mirror the FastAPI backend schemas.
 *
 * Keep in sync with:
 *   web/routers/items.py      (ItemSummary, ItemDetail, ItemListResponse, BulkDeleteResponse)
 *   web/routers/reminders.py  (ReminderResponse)
 *   web/routers/settings.py   (SettingsResponse)
 *   web/routers/auth.py       (TelegramLoginRequest, token response, me response)
 */

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** Payload sent to POST /api/auth/telegram (mirrors TelegramLoginRequest). */
export interface TelegramLoginPayload {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
}

/** Response from POST /api/auth/telegram. */
export interface AuthTokenResponse {
  token: string;
}

/** Response from GET /api/auth/me — JWT claims. */
export interface MeResponse {
  /** User ID as a string (the "sub" claim). */
  sub: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Items
// ---------------------------------------------------------------------------

/** Valid item type values returned by the API. */
export type ItemType = "task" | "note" | "link" | "idea" | "media";

/** Compact item representation used in list responses (mirrors ItemSummary). */
export interface ItemSummary {
  id: string;
  type: ItemType;
  title: string | null;
  preview: string;
  created_at: string;
}

/** Full item representation returned by the detail endpoint (mirrors ItemDetail). */
export interface ItemDetail {
  id: string;
  type: ItemType;
  content: string;
  title: string | null;
  description: string | null;
  scraped_text: string | null;
  created_at: string;
}

/** Paginated list of items (mirrors ItemListResponse). */
export interface ItemListResponse {
  items: ItemSummary[];
  page: number;
  total_pages: number;
}

/** Response for bulk delete — count of items actually deleted (mirrors BulkDeleteResponse). */
export interface BulkDeleteResponse {
  deleted: number;
}

// ---------------------------------------------------------------------------
// Reminders
// ---------------------------------------------------------------------------

/** Valid reminder action values for PATCH /api/reminders/{id}. */
export type ReminderAction =
  | { action: "acknowledge" }
  | { action: "cancel" }
  | { action: "snooze"; snooze_option: "+1h" | "+24h" | "next_day" };

/** Single reminder representation (mirrors ReminderResponse). */
export interface ReminderResponse {
  id: string;
  item_id: string;
  remind_at: string;
  snooze_count: number;
  item_preview: string;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

/** User settings (mirrors SettingsResponse). */
export interface SettingsResponse {
  timezone: string;
  language: string;
}

/** Partial update payload for PATCH /api/settings. */
export interface PatchSettingsRequest {
  timezone?: string;
  language?: string;
}
