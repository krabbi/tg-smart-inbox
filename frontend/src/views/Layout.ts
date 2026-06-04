/**
 * Layout.ts — Top-level shell view for the Foldkit SPA.
 *
 * Renders one of two states:
 *   - Unauthenticated: a login-required placeholder (actual Telegram Login
 *     Widget is added in #188).
 *   - Authenticated: a sidebar (category tabs) on the left and a content
 *     area on the right. The content area is a placeholder <slot> that child
 *     views (#188, #189, #190) will populate.
 *
 * view() is a pure function — it takes the Model and a dispatch callback and
 * returns an HTML string. The runtime in Main.ts sets innerHTML and wires the
 * click listeners produced by attachListeners().
 */

import type { Model, Route } from "../Model.ts";
import type { Msg } from "../Messages.ts";
import { view as loginView, attachLoginListeners } from "./Login.ts";

// ---------------------------------------------------------------------------
// Sidebar tab configuration
// ---------------------------------------------------------------------------

interface TabConfig {
  route: Route;
  label: string;
}

const TABS: TabConfig[] = [
  { route: "all", label: "All" },
  { route: "tasks", label: "Tasks" },
  { route: "notes", label: "Notes" },
  { route: "links", label: "Links" },
  { route: "ideas", label: "Ideas" },
  { route: "reminders", label: "Reminders" },
];

// ---------------------------------------------------------------------------
// View functions
// ---------------------------------------------------------------------------

/**
 * Render the unauthenticated state — the Telegram Login Widget card.
 * Delegates to Login.view() so that widget-specific markup is co-located
 * with its listener wiring in Login.ts.
 */
function viewUnauthenticated(model: Model): string {
  return loginView(model);
}

/**
 * Render a single sidebar tab button.
 * Uses data-route attribute so attachListeners() can bind dispatch without
 * closing over DOM references.
 */
function viewTab(tab: TabConfig, isActive: boolean): string {
  const activeClass = isActive ? " tab--active" : "";
  return `<button class="tab${activeClass}" data-route="${tab.route}">${tab.label}</button>`;
}

/**
 * Render the authenticated shell: sidebar on the left, content area on the right.
 * The content area holds a placeholder until child views are wired in #188/#189/#190.
 */
function viewAuthenticated(model: Model): string {
  const tabsHtml = TABS.map((tab) =>
    viewTab(tab, tab.route === model.currentRoute),
  ).join("\n");

  return `
    <div class="app-shell">
      <nav class="sidebar">
        <div class="sidebar-brand">tg-smart-inbox</div>
        <div class="sidebar-tabs">
          ${tabsHtml}
        </div>
      </nav>
      <main class="content-area">
        <div id="view-slot">
          <p class="content-placeholder">Select a category from the sidebar.</p>
        </div>
      </main>
    </div>
  `.trim();
}

/**
 * Render the error banner when model.error is non-null.
 * The dismiss button dispatches ClearError via data attribute.
 */
function viewErrorBanner(error: string): string {
  return `
    <div class="error-banner">
      <span>${error}</span>
      <button class="error-dismiss" data-action="clear-error">&times;</button>
    </div>
  `.trim();
}

/**
 * Render the full application shell based on current Model state.
 * Returns an HTML string to be set as innerHTML on the root element.
 */
export function view(model: Model): string {
  const errorHtml =
    model.error !== null ? viewErrorBanner(model.error) : "";

  const bodyHtml =
    model.auth.tag === "authenticated"
      ? viewAuthenticated(model)
      : viewUnauthenticated(model);

  return `${errorHtml}${bodyHtml}`;
}

/**
 * Attach DOM event listeners after the view HTML has been injected into the DOM.
 * Must be called every time render() sets innerHTML on the root element.
 *
 * @param root      The root DOM element that was just rendered into.
 * @param dispatch  The dispatch function from the Foldkit runtime.
 */
export function attachListeners(
  root: HTMLElement,
  dispatch: (msg: Msg) => void,
  model: Model,
): void {
  // Sidebar tab buttons — each carries data-route
  root.querySelectorAll<HTMLButtonElement>("button[data-route]").forEach((btn) => {
    const route = btn.dataset["route"] as Route | undefined;
    if (route !== undefined) {
      btn.addEventListener("click", () => {
        dispatch({ type: "NavigateTo", route });
      });
    }
  });

  // Error dismiss button
  root
    .querySelectorAll<HTMLButtonElement>("button[data-action='clear-error']")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        dispatch({ type: "ClearError" });
      });
    });

  // Telegram Login Widget global callback — only needed when unauthenticated
  if (model.auth.tag === "unauthenticated") {
    attachLoginListeners(dispatch);
  }
}
