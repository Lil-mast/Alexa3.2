/**
 * The API origin. Empty means "same origin", which is what the Vite dev proxy
 * gives us. In production VITE_API_BASE points at the deployed API, for
 * example https://alexa-api.onrender.com.
 */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");
