/**
 * ItemList.ts — Paginated item list view with search and delete UI.
 *
 * Rendered when currentRoute is one of: all | tasks | notes | links | ideas.
 * Responsibilities:
 *   - Displays a grid of item cards (title/preview, type badge, date).
 *   - Search bar: submitting dispatches SearchItems; clearing dispatches ClearSearch.
 *   - Clicking a card dispatches SelectItem(id) to open ItemDetail.
 *   - Single delete: trash button on card → confirmation dialog → DeleteItem.
 *   - Bulk delete: checkbox on each card → "Delete selected (N)" button →
 *     confirmation dialog → BulkDeleteItems.
 *   - Empty and nothing-found states.
 *   - Prev/next pagination (hidden when total_pages = 1).
 */

import type { Model } from "../Model.ts";
import type { Msg } from "../Messages.ts";
import type { ItemSummary, ItemType } from "../api/types.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Map an ItemType to a human-readable badge label. */
function typeBadgeLabel(type: ItemType): string {
  switch (type) {
    case "task":
      return "Task";
    case "note":
      return "Note";
    case "link":
      return "Link";
    case "idea":
      return "Idea";
    case "media":
      return "Media";
  }
}

/** Format an ISO date string to a short locale date. */
function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

/** Escape HTML special characters in user-sourced strings. */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------------------
// Sub-views
// ---------------------------------------------------------------------------

function viewSearchBar(query: string): string {
  const escaped = escapeHtml(query);
  return `
    <form class="search-bar" data-action="search-form">
      <input
        class="search-input"
        type="search"
        name="q"
        placeholder="Search&hellip;"
        value="${escaped}"
        autocomplete="off"
      />
      <button class="btn btn-primary search-submit" type="submit">Search</button>
      ${
        query !== ""
          ? `<button class="btn btn-secondary search-clear" type="button" data-action="clear-search">Clear</button>`
          : ""
      }
    </form>
  `.trim();
}

function viewEmptyState(query: string): string {
  if (query !== "") {
    return `<p class="list-empty-state">No results for &laquo;${escapeHtml(query)}&raquo;</p>`;
  }
  return `<p class="list-empty-state">No items here yet.</p>`;
}

function viewItemCard(item: ItemSummary, isChecked: boolean): string {
  const title =
    item.title !== null && item.title !== ""
      ? escapeHtml(item.title)
      : escapeHtml(item.preview);
  const preview =
    item.title !== null && item.title !== "" ? escapeHtml(item.preview) : "";

  const checkedAttr = isChecked ? " checked" : "";

  return `
    <div class="item-card${isChecked ? " item-card--checked" : ""}" data-id="${escapeHtml(item.id)}">
      <label class="item-card-checkbox-label" title="Select for bulk delete">
        <input
          class="item-card-checkbox"
          type="checkbox"
          data-action="toggle-check"
          data-id="${escapeHtml(item.id)}"
          ${checkedAttr}
        />
      </label>
      <div class="item-card-body" data-action="select-item" data-id="${escapeHtml(item.id)}">
        <div class="item-card-header">
          <span class="type-badge type-badge--${item.type}">${typeBadgeLabel(item.type)}</span>
          <span class="item-card-date">${formatDate(item.created_at)}</span>
        </div>
        <p class="item-card-title">${title}</p>
        ${preview !== "" ? `<p class="item-card-preview">${preview}</p>` : ""}
      </div>
      <button
        class="btn btn-danger-icon item-card-delete"
        title="Delete this item"
        data-action="request-delete"
        data-id="${escapeHtml(item.id)}"
      >&#128465;</button>
    </div>
  `.trim();
}

function viewPagination(page: number, totalPages: number): string {
  if (totalPages <= 1) return "";
  return `
    <div class="pagination">
      <button
        class="btn btn-secondary"
        data-action="prev-page"
        data-page="${page - 1}"
        ${page <= 1 ? "disabled" : ""}
      >&#8592; Prev</button>
      <span class="pagination-info">Page ${page} of ${totalPages}</span>
      <button
        class="btn btn-secondary"
        data-action="next-page"
        data-page="${page + 1}"
        ${page >= totalPages ? "disabled" : ""}
      >Next &#8594;</button>
    </div>
  `.trim();
}

function viewBulkDeleteBar(checkedCount: number): string {
  if (checkedCount === 0) return "";
  return `
    <div class="bulk-delete-bar">
      <span class="bulk-delete-count">${checkedCount} selected</span>
      <button class="btn btn-danger" data-action="request-bulk-delete">
        Delete selected (${checkedCount})
      </button>
    </div>
  `.trim();
}

function viewDeleteConfirmDialog(model: Model): string {
  const { deleteConfirm } = model.itemList;
  if (deleteConfirm.tag === "none") return "";

  const isBulk = deleteConfirm.tag === "bulk";
  const message = isBulk
    ? `Delete ${deleteConfirm.ids.length} items? This cannot be undone.`
    : "Delete this item? This cannot be undone.";
  const confirmAction = isBulk ? "confirm-bulk-delete" : "confirm-delete-item";

  return `
    <div class="dialog-overlay">
      <div class="dialog">
        <p class="dialog-message">${escapeHtml(message)}</p>
        <div class="dialog-actions">
          <button class="btn btn-danger" data-action="${confirmAction}">Delete</button>
          <button class="btn btn-secondary" data-action="cancel-delete">Cancel</button>
        </div>
      </div>
    </div>
  `.trim();
}

function viewFeedback(feedback: string): string {
  return `
    <div class="feedback-banner">
      <span>${escapeHtml(feedback)}</span>
      <button class="btn-icon feedback-dismiss" data-action="clear-item-feedback">&times;</button>
    </div>
  `.trim();
}

function viewLoadingState(): string {
  return `<div class="list-loading">Loading&hellip;</div>`;
}

// ---------------------------------------------------------------------------
// Public view
// ---------------------------------------------------------------------------

/**
 * Render the full item list panel including search bar, cards, pagination,
 * bulk-delete bar, delete confirmation dialog, and feedback banner.
 */
export function view(model: Model): string {
  const { itemList } = model;
  const checkedCount = itemList.checkedIds.size;

  const feedbackHtml =
    itemList.feedback !== null ? viewFeedback(itemList.feedback) : "";

  const confirmDialogHtml = viewDeleteConfirmDialog(model);

  const searchHtml = viewSearchBar(itemList.searchQuery);

  let contentHtml: string;
  if (itemList.isLoading) {
    contentHtml = viewLoadingState();
  } else if (itemList.items.length === 0) {
    contentHtml = viewEmptyState(itemList.searchQuery);
  } else {
    const cardsHtml = itemList.items
      .map((item) => viewItemCard(item, itemList.checkedIds.has(item.id)))
      .join("\n");
    contentHtml = `<div class="item-list">${cardsHtml}</div>`;
  }

  const paginationHtml = viewPagination(itemList.page, itemList.total_pages);
  const bulkBarHtml = viewBulkDeleteBar(checkedCount);

  return `
    <div class="item-list-view">
      ${feedbackHtml}
      ${searchHtml}
      ${bulkBarHtml}
      ${contentHtml}
      ${paginationHtml}
      ${confirmDialogHtml}
    </div>
  `.trim();
}

// ---------------------------------------------------------------------------
// Listener wiring
// ---------------------------------------------------------------------------

/**
 * Attach DOM event listeners for the item list panel.
 * Must be called every time the list view is rendered into the DOM.
 */
export function attachListListeners(
  root: HTMLElement,
  dispatch: (msg: Msg) => void,
): void {
  // Search form submit
  root.querySelectorAll<HTMLFormElement>("form[data-action='search-form']").forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = form.querySelector<HTMLInputElement>("input[name='q']");
      const q = input !== null ? input.value.trim() : "";
      if (q === "") {
        dispatch({ type: "ClearSearch" });
      } else {
        dispatch({ type: "SearchItems", q });
      }
    });
  });

  // Clear search button
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='clear-search']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        dispatch({ type: "ClearSearch" });
      });
    });

  // Item card body click → select item
  root
    .querySelectorAll<HTMLElement>("[data-action='select-item']")
    .forEach((el) => {
      el.addEventListener("click", () => {
        const id = el.dataset["id"];
        if (id !== undefined) {
          dispatch({ type: "SelectItem", id });
        }
      });
    });

  // Checkbox toggle
  root
    .querySelectorAll<HTMLInputElement>("input[data-action='toggle-check']")
    .forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        const id = checkbox.dataset["id"];
        if (id !== undefined) {
          dispatch({ type: "ToggleItemCheck", id });
        }
      });
    });

  // Single delete button
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='request-delete']")
    .forEach((btn) => {
      btn.addEventListener("click", (e) => {
        // Prevent the click from bubbling to the card body and triggering SelectItem.
        e.stopPropagation();
        const id = btn.dataset["id"];
        if (id !== undefined) {
          dispatch({ type: "RequestDeleteItem", id });
        }
      });
    });

  // Confirm single delete
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='confirm-delete-item']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        dispatch({ type: "ConfirmDeleteItem" });
      });
    });

  // Request bulk delete
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='request-bulk-delete']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        dispatch({ type: "RequestBulkDelete" });
      });
    });

  // Confirm bulk delete
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='confirm-bulk-delete']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        dispatch({ type: "ConfirmBulkDelete" });
      });
    });

  // Cancel any delete dialog
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='cancel-delete']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        dispatch({ type: "CancelDelete" });
      });
    });

  // Pagination — prev/next
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='prev-page'], button[data-action='next-page']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        const page = parseInt(btn.dataset["page"] ?? "1", 10);
        if (!isNaN(page)) {
          dispatch({ type: "ChangePage", page });
        }
      });
    });

  // Feedback dismiss
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='clear-item-feedback']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        dispatch({ type: "ClearItemFeedback" });
      });
    });
}
