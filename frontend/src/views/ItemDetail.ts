/**
 * ItemDetail.ts — Full item detail panel view.
 *
 * Rendered in the content area when an item is selected (model.itemList.selectedItemId
 * is non-null and the item has been loaded via GET /api/items/{id}).
 *
 * Shows: title, type badge, created_at, full content, description, and
 * scraped_text (Link items only). A Back button returns to the item list.
 */

import type { Model } from "../Model.ts";
import type { Msg } from "../Messages.ts";
import type { ItemDetail as ItemDetailData, ItemType } from "../api/types.ts";

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

/** Format an ISO date string to a human-friendly locale date. */
function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
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

/** Escape HTML special characters to prevent XSS when rendering user content. */
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

function viewLoadingState(): string {
  return `<div class="item-detail-loading">Loading item&hellip;</div>`;
}

function viewNotFound(): string {
  return `
    <div class="item-detail-empty">
      <p>Item not found.</p>
    </div>
  `.trim();
}

function viewDetail(item: ItemDetailData): string {
  const title = item.title !== null ? escapeHtml(item.title) : "(no title)";
  const content = escapeHtml(item.content);

  const descriptionHtml =
    item.description !== null
      ? `
        <section class="item-detail-section">
          <h3 class="item-detail-section-label">Description</h3>
          <p class="item-detail-section-body">${escapeHtml(item.description)}</p>
        </section>`
      : "";

  // scraped_text is only meaningful for Link items
  const scrapedHtml =
    item.type === "link" && item.scraped_text !== null
      ? `
        <section class="item-detail-section">
          <h3 class="item-detail-section-label">Scraped page text</h3>
          <pre class="item-detail-scraped">${escapeHtml(item.scraped_text)}</pre>
        </section>`
      : "";

  return `
    <div class="item-detail">
      <div class="item-detail-header">
        <button class="btn btn-secondary" data-action="back-to-list">&#8592; Back</button>
        <span class="type-badge type-badge--${item.type}">${typeBadgeLabel(item.type)}</span>
      </div>
      <h2 class="item-detail-title">${title}</h2>
      <p class="item-detail-meta">${formatDate(item.created_at)}</p>
      <section class="item-detail-section">
        <h3 class="item-detail-section-label">Content</h3>
        <p class="item-detail-section-body">${content}</p>
      </section>
      ${descriptionHtml}
      ${scrapedHtml}
    </div>
  `.trim();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Render the item detail panel.
 *
 * If the item data is not yet loaded (selectedItemId is set but items array
 * doesn't contain a matching full detail), show a loading state. The actual
 * ItemDetail data is stored separately in model.itemList via ItemLoaded.
 */
export function view(model: Model, loadedItem: ItemDetailData | null): string {
  if (model.itemList.selectedItemId === null) {
    return viewNotFound();
  }
  if (loadedItem === null) {
    return viewLoadingState();
  }
  return viewDetail(loadedItem);
}

/**
 * Attach DOM event listeners for the detail panel.
 * Must be called every time the detail view is rendered.
 */
export function attachDetailListeners(
  root: HTMLElement,
  dispatch: (msg: Msg) => void,
): void {
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='back-to-list']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        dispatch({ type: "BackToList" });
      });
    });
}
