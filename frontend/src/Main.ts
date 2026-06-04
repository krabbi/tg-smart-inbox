/**
 * Main.ts — Foldkit application entry point.
 *
 * Wires the Elm Architecture triad: Model / update / view.
 *
 * Init behaviour:
 *   - No JWT in localStorage → render login placeholder immediately, no API call.
 *   - JWT present → call GET /api/auth/me to validate:
 *       200  → dispatch MeLoaded (sets auth to authenticated)
 *       401  → clearJwt() is called inside apiRequest; dispatches SessionExpired
 *
 * SessionExpired → clears JWT from localStorage, returns to unauthenticated state.
 */

import { getJwt, setJwt, clearJwt, type Command } from "./api/client.ts";
import { apiRequest } from "./api/client.ts";
import type { MeResponse, TelegramLoginPayload } from "./api/types.ts";
import { initialModel, type Model } from "./Model.ts";
import type { Msg } from "./Messages.ts";
import { view, attachListeners } from "./views/Layout.ts";
import { postTelegramAuth } from "./api/auth.ts";

// ---------------------------------------------------------------------------
// update — pure function: (Model, Msg) → Model
// ---------------------------------------------------------------------------

/**
 * Return the next Model given the current Model and a dispatched Msg.
 * All state transitions are expressed here; no side effects.
 */
function update(model: Model, msg: Msg): Model {
  switch (msg.type) {
    case "TelegramLoginSuccess":
      // Raw Telegram payload received — wait for the POST /api/auth/telegram
      // response before marking the user as authenticated.
      return { ...model, isLoading: true, error: null };

    case "AuthSuccess":
      setJwt(msg.token);
      return {
        ...model,
        auth: { tag: "authenticated", token: msg.token, user: msg.user },
        isLoading: false,
        error: null,
      };

    case "MeLoaded":
      // JWT was valid on startup — restore authenticated state.
      return {
        ...model,
        auth: {
          tag: "authenticated",
          token: getJwt() ?? "",
          user: msg.user,
        },
        isLoading: false,
        error: null,
      };

    case "AuthFailed":
      return {
        ...model,
        auth: { tag: "unauthenticated" },
        isLoading: false,
        error: msg.reason,
      };

    case "SessionExpired":
      // clearJwt() is already called inside apiRequest on 401; mirror the
      // state here to keep Model and localStorage in sync.
      clearJwt();
      return {
        ...model,
        auth: { tag: "unauthenticated" },
        isLoading: false,
        error: null,
      };

    case "AccessDenied":
      return {
        ...model,
        auth: { tag: "unauthenticated" },
        isLoading: false,
        error: "Access denied — your account is not whitelisted.",
      };

    case "NavigateTo":
      return { ...model, currentRoute: msg.route };

    case "ClearError":
      return { ...model, error: null };
  }
}

// ---------------------------------------------------------------------------
// Command helpers
// ---------------------------------------------------------------------------

/**
 * Build a Command that validates the stored JWT via GET /api/auth/me.
 * On success dispatches MeLoaded; on failure dispatches SessionExpired
 * (which is the canonical Msg for 401 responses from apiRequest).
 */
function validateStoredJwt(): Command<Msg> {
  return apiRequest<Msg, MeResponse>(
    "/api/auth/me",
    { method: "GET" },
    (data) => ({ type: "MeLoaded", user: data }),
    (err) => {
      if (err.type === "SessionExpired") {
        return { type: "SessionExpired" };
      }
      if (err.type === "AccessDenied") {
        return { type: "AccessDenied" };
      }
      // Any other HTTP error on startup — treat as session gone.
      return { type: "SessionExpired" };
    },
  );
}

/**
 * Build a Command<Msg> that POSTs the Telegram Login Widget payload to the
 * backend and then fetches /api/auth/me with the returned JWT to obtain the
 * full user object.
 *
 * Flow:
 *   POST /api/auth/telegram  → token
 *   GET  /api/auth/me        → user  → dispatch AuthSuccess(token, user)
 *
 * Error mapping:
 *   403  → AuthFailed("Access denied — you are not on the allowed list")
 *   any  → AuthFailed("Login failed — invalid or expired data, please try again")
 */
function telegramAuthCommand(payload: TelegramLoginPayload): Command<Msg> {
  return {
    run(dispatch) {
      postTelegramAuth(payload).run((authMsg) => {
        if (authMsg.type === "AuthSuccess") {
          // Store the JWT so the follow-up GET /api/auth/me can attach it.
          setJwt(authMsg.token);
          apiRequest<Msg, MeResponse>(
            "/api/auth/me",
            { method: "GET" },
            (data) => ({ type: "AuthSuccess", token: authMsg.token, user: data }),
            (err) => {
              if (err.type === "AccessDenied") {
                return {
                  type: "AuthFailed",
                  reason: "Access denied — you are not on the allowed list",
                };
              }
              return {
                type: "AuthFailed",
                reason: "Login failed — invalid or expired data, please try again",
              };
            },
          ).run(dispatch);
        } else {
          // authMsg.type === "AuthError"
          const err = authMsg.err;
          if (err.type === "AccessDenied") {
            dispatch({
              type: "AuthFailed",
              reason: "Access denied — you are not on the allowed list",
            });
          } else {
            dispatch({
              type: "AuthFailed",
              reason: "Login failed — invalid or expired data, please try again",
            });
          }
        }
      });
    },
  };
}

// ---------------------------------------------------------------------------
// Runtime — minimal Foldkit-style loop
// ---------------------------------------------------------------------------

/**
 * Mount the application on the DOM element with the given id.
 * Sets up the render loop and runs the init command if a JWT is present.
 */
function mount(rootId: string): void {
  const root = document.getElementById(rootId);
  if (root === null) {
    throw new Error(`mount: element #${rootId} not found`);
  }

  let model = initialModel;

  function render(): void {
    root!.innerHTML = view(model);
    attachListeners(root!, dispatch, model);
  }

  function dispatch(msg: Msg): void {
    model = update(model, msg);
    render();
    // Fire side-effecting commands that cannot live in the pure update().
    if (msg.type === "TelegramLoginSuccess") {
      runCommand(telegramAuthCommand(msg.payload));
    }
  }

  function runCommand(cmd: Command<Msg>): void {
    cmd.run(dispatch);
  }

  // Initial render
  render();

  // If a JWT is already stored, validate it immediately — no extra network
  // call if the token is absent.
  const storedToken = getJwt();
  if (storedToken !== null) {
    model = { ...model, isLoading: true };
    render();
    runCommand(validateStoredJwt());
  }
}

mount("app");
