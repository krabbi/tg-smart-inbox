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

// ---------------------------------------------------------------------------
// View
// ---------------------------------------------------------------------------

/**
 * Render the login card containing the Telegram Login Widget script tag.
 *
 * The widget is rendered as an inline <script> so that Telegram's loader can
 * locate the script element and replace it with the actual button iframe.
 * The data-onauth attribute names the global callback defined below.
 */
export function view(model: Model): string {
  if (BOT_USERNAME === "") {
    console.warn(
      "Login.ts: VITE_BOT_USERNAME is not set — Telegram Login Widget will not work.",
    );
  }

  const loadingHtml = model.isLoading
    ? `<p class="login-loading">Signing in&hellip;</p>`
    : "";

  return `
    <div class="login-container">
      <div class="login-card">
        <h1 class="login-title">tg-smart-inbox</h1>
        <p class="login-subtitle">Sign in with your Telegram account</p>
        ${loadingHtml}
        <div id="telegram-login-widget">
          <script
            async
            src="https://telegram.org/js/telegram-widget.js?22"
            data-telegram-login="${BOT_USERNAME}"
            data-size="large"
            data-onauth="onTelegramAuth"
            data-request-access="write"
          ></script>
        </div>
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
}
