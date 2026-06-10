/**
 * Login.ts — Unauthenticated landing page with Telegram Login Widget.
 *
 * Renders the official Telegram Login Widget script tag. When the user
 * authorises via Telegram, the widget calls window.onTelegramAuth(user),
 * which dispatches TelegramLoginSuccess into the Foldkit update loop.
 *
 * The bot username is read from the VITE_BOT_USERNAME build-time env var.
 * Set it in frontend/.env.local (development) or in the CI/CD environment:
 *
 *   VITE_BOT_USERNAME=your_bot_username
 *
 * If the variable is not set the widget renders with an empty data-telegram-login
 * attribute and Telegram will reject the embed — a warning is logged.
 */

import type { Msg } from "../Messages.ts";
import type { TelegramLoginPayload } from "../api/types.ts";
import type { Model } from "../Model.ts";

// ---------------------------------------------------------------------------
// Bot username — injected at build time by Vite
// ---------------------------------------------------------------------------

const BOT_USERNAME: string = import.meta.env["VITE_BOT_USERNAME"] ?? "";
if (BOT_USERNAME === "") {
  console.warn(
    "Login.ts: VITE_BOT_USERNAME is not set — Telegram Login Widget will not work.",
  );
}

// ---------------------------------------------------------------------------
// View
// ---------------------------------------------------------------------------

/**
 * Render the login card with an empty container for the Telegram Login Widget.
 *
 * The widget <script> element cannot be part of this HTML string: the runtime
 * injects views via innerHTML, and scripts inserted through innerHTML are never
 * executed by the browser. Instead, attachLoginListeners() creates the script
 * element programmatically and appends it into #telegram-login-widget after
 * every render.
 */
export function view(model: Model): string {
  const loadingHtml = model.isLoading
    ? `<p class="login-loading">Signing in&hellip;</p>`
    : "";

  return `
    <div class="login-container">
      <div class="login-card">
        <h1 class="login-title">tg-smart-inbox</h1>
        <p class="login-subtitle">Sign in with your Telegram account</p>
        ${loadingHtml}
        <div id="telegram-login-widget"></div>
      </div>
    </div>
  `.trim();
}

// ---------------------------------------------------------------------------
// Window callback registration
// ---------------------------------------------------------------------------

/**
 * Register window.onTelegramAuth so the Telegram Login Widget can call it.
 * Must be called once after the login view is mounted into the DOM.
 * Subsequent calls (on re-render) are safe — they overwrite the same property.
 *
 * @param dispatch  The Foldkit dispatch function from the runtime.
 */
export function attachLoginListeners(
  dispatch: (msg: Msg) => void,
): void {
  (window as Window & { onTelegramAuth?: (user: TelegramLoginPayload) => void }).onTelegramAuth =
    (user: TelegramLoginPayload) => {
      dispatch({ type: "TelegramLoginSuccess", payload: user });
    };

  injectWidgetScript();
}

/**
 * Create the Telegram Login Widget <script> element programmatically and
 * append it into the #telegram-login-widget container.
 *
 * Scripts inserted via innerHTML are inert, so this is the only way the widget
 * loader can run after a render. Each render wipes the container, so the
 * script is re-appended every time; the emptiness check guards against
 * double-injection within a single render cycle.
 */
function injectWidgetScript(): void {
  const container = document.getElementById("telegram-login-widget");
  if (container === null || container.childElementCount > 0) {
    return;
  }

  const script = document.createElement("script");
  script.async = true;
  script.src = "https://telegram.org/js/telegram-widget.js?22";
  script.setAttribute("data-telegram-login", BOT_USERNAME);
  script.setAttribute("data-size", "large");
  script.setAttribute("data-onauth", "onTelegramAuth(user)");
  script.setAttribute("data-request-access", "write");
  container.appendChild(script);
}
