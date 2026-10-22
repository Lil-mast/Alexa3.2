/**
 * Browser account API.
 *
 * The flow has four steps and they live on two origins:
 *
 *   1. GET  /api/auth/config          is Google sign-in configured at all
 *   2. GET  /api/auth/google/start    the browser goes to Google
 *   3. GET  /api/auth/callback/google the API hands the browser a one-time
 *                                      code and redirects to /#/auth/callback
 *   4. POST /api/auth/exchange        the code becomes a session token
 *
 * The session token never appears in a URL. It is held in sessionStorage and
 * sent as a bearer header, exactly like the operator token.
 */
import { API_BASE } from "./base";

export interface AuthConfig {
  enabled: boolean;
  provider: "google";
  login_url: string | null;
  frontend_url: string;
  session_ttl_seconds: number;
  dev_login: boolean;
  /** Names of the settings the API is missing. Never values. */
  missing?: string[];
}

export interface AuthUser {
  id: number | string;
  subject: string;
  email: string;
  display_name: string | null;
  provider: string;
}

export interface AuthSession {
  token: string;
  token_type: "bearer";
  expires_at: number;
  subject: string;
  user: AuthUser;
  demo_notice: string;
}

export interface AuthMe {
  authenticated: boolean;
  auth_type: "session" | "token";
  subject: string;
  user: AuthUser | null;
  session_expires_at: number | null;
  demo_notice: string;
}

export class AuthApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly followUp: string;

  constructor(status: number, code: string, message: string, followUp = "") {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
    this.code = code;
    this.followUp = followUp;
  }
}

const TIMEOUT_MS = 8_000;

async function parseError(response: Response): Promise<AuthApiError> {
  let code = `http_${response.status}`;
  let message = "The sign-in service is not answering.";
  let followUp = "";

  try {
    const body = (await response.json()) as {
      detail?: { code?: string; message?: string; follow_up?: string };
    };
    const detail = body?.detail;
    if (detail && typeof detail === "object") {
      code = detail.code ?? code;
      message = detail.message ?? message;
      followUp = detail.follow_up ?? "";
    }
  } catch {
    // A non-JSON error body tells us nothing useful, so keep the default.
  }

  return new AuthApiError(response.status, code, message, followUp);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    throw new AuthApiError(0, "network_error", "The sign-in service is unreachable.");
  }

  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as T;
}

export const authApi = {
  config: () => request<AuthConfig>("/api/auth/config"),

  exchange: (code: string) =>
    request<AuthSession>("/api/auth/exchange", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  me: (token: string) =>
    request<AuthMe>("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    }),

  logout: (token: string) =>
    request<null>("/api/auth/logout", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),
};
