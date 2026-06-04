/**
 * items.ts — API commands for item endpoints.
 *
 * GET    /api/items          — paginated list with optional type/search filters
 * GET    /api/items/{id}     — single item detail
 * DELETE /api/items/{id}     — delete one item (204 No Content)
 * DELETE /api/items          — bulk delete (returns deleted count)
 */

import { apiRequest, type Command, type HttpErrorMsg } from "./client.ts";
import type {
  BulkDeleteResponse,
  ItemDetail,
  ItemListResponse,
  ItemType,
} from "./types.ts";

// ---------------------------------------------------------------------------
// Message types produced by item commands
// ---------------------------------------------------------------------------

export type ItemsMsg =
  | { type: "ItemsLoaded"; data: ItemListResponse }
  | { type: "ItemLoaded"; data: ItemDetail }
  | { type: "ItemDeleted"; id: string }
  | { type: "ItemsBulkDeleted"; deleted: number }
  | { type: "ItemsError"; err: HttpErrorMsg };

// ---------------------------------------------------------------------------
// Query params for list endpoint
// ---------------------------------------------------------------------------

export interface GetItemsParams {
  /** Filter by item type. */
  type?: ItemType;
  /** Page number (1-based). */
  page?: number;
  /** Full-text search query. */
  q?: string;
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

/**
 * Return a Command that GETs /api/items with optional filters and dispatches
 * ItemsLoaded on success or ItemsError on failure.
 */
export function getItems(params: GetItemsParams = {}): Command<ItemsMsg> {
  const searchParams = new URLSearchParams();
  if (params.type !== undefined) searchParams.set("type", params.type);
  if (params.page !== undefined) searchParams.set("page", String(params.page));
  if (params.q !== undefined && params.q !== "") searchParams.set("q", params.q);

  const query = searchParams.toString();
  const path = query ? `/api/items?${query}` : "/api/items";

  return apiRequest<ItemsMsg, ItemListResponse>(
    path,
    { method: "GET" },
    (data) => ({ type: "ItemsLoaded", data }),
    (err) => ({ type: "ItemsError", err }),
  );
}

/**
 * Return a Command that GETs /api/items/{id} and dispatches ItemLoaded on
 * success or ItemsError on failure.
 */
export function getItem(id: string): Command<ItemsMsg> {
  return apiRequest<ItemsMsg, ItemDetail>(
    `/api/items/${encodeURIComponent(id)}`,
    { method: "GET" },
    (data) => ({ type: "ItemLoaded", data }),
    (err) => ({ type: "ItemsError", err }),
  );
}

/**
 * Return a Command that DELETEs /api/items/{id} (204) and dispatches
 * ItemDeleted on success or ItemsError on failure.
 */
export function deleteItem(id: string): Command<ItemsMsg> {
  return apiRequest<ItemsMsg, null>(
    `/api/items/${encodeURIComponent(id)}`,
    { method: "DELETE" },
    () => ({ type: "ItemDeleted", id }),
    (err) => ({ type: "ItemsError", err }),
  );
}

/**
 * Return a Command that DELETEs /api/items (bulk) and dispatches
 * ItemsBulkDeleted (with count) on success or ItemsError on failure.
 */
export function bulkDeleteItems(ids: string[]): Command<ItemsMsg> {
  return apiRequest<ItemsMsg, BulkDeleteResponse>(
    "/api/items",
    { method: "DELETE", body: { ids } },
    (data) => ({ type: "ItemsBulkDeleted", deleted: data.deleted }),
    (err) => ({ type: "ItemsError", err }),
  );
}
