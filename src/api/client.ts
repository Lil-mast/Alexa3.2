import { readSessionToken } from "../auth/session";
import { API_BASE } from "./base";
import type {
  AuditList,
  AuditVerify,
  Health,
  HouseState,
  ToolList,
  TraceList,
  VoiceConfig,
  WhoAmI,
  AssistantReply,
} from "./types";

const TOKEN_KEY = "alexa.console.token";
const REQUEST_TIMEOUT_MS = 8_000;

/**
 * The console reads the operator token from sessionStorage, never from
 * localStorage and never from a build artifact. `VITE_CONSOLE_TOKEN` exists for
 * local development only; it is compiled into the bundle, so it must not be set
 * for a deployed build.
 */
export function readToken(): string {
  // An operator token pasted into the console wins, because it is the
  // deliberate choice for that screen.
  const operator = window.sessionStorage.getItem(TOKEN_KEY) ?? "";
  if (operator) {
    return operator;
  }
  // Otherwise the signed-in browser session works, so "under the hood" needs
  // no second credential.
  const session = readSessionToken();
  if (session) {
    return session;
  }
  return import.meta.env.VITE_CONSOLE_TOKEN ?? "";
}

export function writeToken(token: string): void {
  if (token) {
    window.sessionStorage.setItem(TOKEN_KEY, token);
  } else {
    window.sessionStorage.removeItem(TOKEN_KEY);
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly challenge: string | null;

  constructor(status: number, message: string, challenge: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.challenge = challenge;
  }
}

function messageFor(status: number): string {
  if (status === 401) {
    return "The operator token is missing or not accepted.";
  }
  if (status === 403) {
    return "This token does not carry the scope for that read.";
  }
  if (status === 404) {
    return "The server does not expose that endpoint.";
  }
  if (status >= 500) {
    return `The server failed with status ${status}.`;
  }
  return `The request failed with status ${status}.`;
}

async function request<T>(path: string): Promise<T> {
  const token = readToken();
  const headers = new Headers({ Accept: "application/json" });
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new ApiError(0, "The server did not answer in time.");
    }
    throw new ApiError(0, "The server is unreachable.");
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      messageFor(response.status),
      response.headers.get("www-authenticate"),
    );
  }

  return (await response.json()) as T;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const token = readToken();
  const headers = new Headers({ Accept: "application/json" });
  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new ApiError(0, "The server did not answer in time.");
    }
    throw new ApiError(0, "The server is unreachable.");
  }

  if (!response.ok) {
    throw new ApiError(response.status, messageFor(response.status));
  }
  return (await response.json()) as T;
}

async function requestAudio(path: string, body: unknown): Promise<Blob> {
  const token = readToken();
  const headers = new Headers({ Accept: "audio/mpeg" });
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: new Headers([...headers.entries(), ["Content-Type", "application/json"]]),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new ApiError(0, "Voice audio is unavailable.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, "Voice audio is unavailable.");
  }
  return response.blob();
}

/** Read-only calls. Tool calls go through one endpoint, which is not built yet. */
export const api = {
  health: () => request<Health>("/health"),
  whoami: () => request<WhoAmI>("/api/whoami"),
  tools: () => request<ToolList>("/api/tools"),
  trace: (limit = 50) => request<TraceList>(`/api/trace?limit=${limit}`),
  audit: (limit = 50) => request<AuditList>(`/api/audit?limit=${limit}`),
  verify: () => request<AuditVerify>("/api/audit/verify"),
  house: () => request<HouseState>("/api/state"),
  voiceConfig: () => request<VoiceConfig>("/api/voice/config"),
  assistantTurn: (utterance: string) => post<AssistantReply>("/api/assistant/turn", { utterance }),
  assistantConfirm: () => post<AssistantReply>("/api/assistant/confirm"),
  assistantCancel: () => post<AssistantReply>("/api/assistant/cancel"),
  speak: (text: string) => requestAudio("/api/voice/speak", { text }),
};
