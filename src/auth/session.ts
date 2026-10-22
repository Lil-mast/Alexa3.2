/**
 * One session token is shared by the public app and the operator console.
 * It lives in sessionStorage, never localStorage and never a build artifact.
 *
 * The Google sign-in callback will write this key after it exchanges the
 * one-time code. The landing page only ever reads it to decide where the
 * primary call to action should point.
 */
import { API_BASE } from "../api/base";

export const SESSION_TOKEN_KEY = "alexa.session.token";

const SESSION_TIMEOUT_MS = 8_000;

export type SessionCheck = "valid" | "invalid" | "unavailable";

export function readSessionToken(): string {
  try {
    return window.sessionStorage.getItem(SESSION_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function writeSessionToken(token: string): void {
  try {
    if (token) {
      window.sessionStorage.setItem(SESSION_TOKEN_KEY, token);
    } else {
      window.sessionStorage.removeItem(SESSION_TOKEN_KEY);
    }
  } catch {
    // A browser that blocks storage still gets an anonymous landing page.
  }
}

export function clearSessionToken(): void {
  writeSessionToken("");
}

/**
 * Ask the server, not the browser, whether the token is still good.
 * An unreachable server is "unavailable", not "invalid", so a temporary
 * network problem never destroys a valid session.
 */
export async function checkSession(token: string): Promise<SessionCheck> {
  if (!token) {
    return "invalid";
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/whoami`, {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      },
      signal: AbortSignal.timeout(SESSION_TIMEOUT_MS),
    });
  } catch {
    return "unavailable";
  }

  if (response.ok) {
    return "valid";
  }
  if (response.status === 401 || response.status === 403) {
    return "invalid";
  }
  return "unavailable";
}
