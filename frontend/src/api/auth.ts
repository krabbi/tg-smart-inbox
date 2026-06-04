/**
 * auth.ts — API commands for authentication endpoints.
 *
 * POST /api/auth/telegram  — exchange a Telegram Login Widget payload for a JWT
 * GET  /api/auth/me        — return the current user's JWT claims
 */

import { apiRequest, type Command, type HttpErrorMsg } from "./client.ts";
import type {
  AuthTokenResponse,
  MeResponse,
  TelegramLoginPayload,
} from "./types.ts";

// ---------------------------------------------------------------------------
// Message types produced by auth commands
// ---------------------------------------------------------------------------

export type AuthMsg =
  | { type: "AuthSuccess"; token: string }
  | { type: "MeLoaded"; user: MeResponse }
  | { type: "AuthError"; err: HttpErrorMsg };

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

/**
 * Return a Command that POSTs a Telegram Login Widget payload and dispatches
 * AuthSuccess (with the JWT) on success or AuthError on failure.
 */
export function postTelegramAuth(
  payload: TelegramLoginPayload,
): Command<AuthMsg> {
  return apiRequest<AuthMsg, AuthTokenResponse>(
    "/api/auth/telegram",
    { method: "POST", body: payload, anonymous: true },
    (data) => ({ type: "AuthSuccess", token: data.token }),
    (err) => ({ type: "AuthError", err }),
  );
}

/**
 * Return a Command that GETs /api/auth/me and dispatches MeLoaded on success
 * or AuthError on failure.
 */
export function getMe(): Command<AuthMsg> {
  return apiRequest<AuthMsg, MeResponse>(
    "/api/auth/me",
    { method: "GET" },
    (data) => ({ type: "MeLoaded", user: data }),
    (err) => ({ type: "AuthError", err }),
  );
}
