import { useEffect, useState } from "react";

import { API_BASE } from "../api/base";
import { authApi } from "../api/auth";
import type { AuthConfig } from "../api/auth";

export type AuthMode = "signup" | "login";

const ERROR_COPY: Record<string, string> = {
  auth_unavailable: "Google sign-in is not configured on this server yet.",
  not_configured: "Google sign-in is not configured on this server yet.",
  invalid_state: "That sign-in request expired before it finished. Try again.",
  oauth_failed: "Google sign-in could not be completed. Try again.",
  invalid_callback: "The sign-in link is incomplete. Try again.",
  invalid_exchange_code: "That sign-in code has already been used. Try again.",
  email_unverified: "Verify the email address with Google, then try again.",
};

/** The published Google mark. It is only ever used on the sign-in button. */
function GoogleMark() {
  return (
    <svg className="lp-google-mark" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

const COPY: Record<AuthMode, {
  eyebrow: string;
  title: string;
  lede: string;
  button: string;
  switchLine: string;
  switchLink: string;
  switchHref: string;
  note: string;
  steps: Array<{ label: string; text: string }>;
}> = {
  signup: {
    eyebrow: "Sign up",
    title: "Open the house.",
    lede: "One Google tap and the simulation is yours. No password, no card, no tour of a settings page first.",
    button: "Continue with Google",
    switchLine: "Already have an account?",
    switchLink: "Log in",
    switchHref: "#/login",
    note: "We use your Google account to sign you in, so we learn your name and your email address. That is the whole of it. Your session token stays in this browser tab, the audit chain records what the house did, and the microphone stays off until you ask for it.",
    steps: [
      { label: "01", text: "Google confirms who you are. We never see your password." },
      { label: "02", text: "The server creates a session for this tab and forgets the one-time code." },
      { label: "03", text: "The house opens with your own audit chain and your own privacy settings." },
    ],
  },
  login: {
    eyebrow: "Log in",
    title: "Welcome back.",
    lede: "Sign in with the same Google account and the house picks up where you left it.",
    button: "Continue with Google",
    switchLine: "New here?",
    switchLink: "Create an account",
    switchHref: "#/signup",
    note: "Signing in creates a new session token in this tab. The old one is replaced, and the house starts clean, but your account and your audit history stay.",
    steps: [
      { label: "01", text: "Google confirms who you are." },
      { label: "02", text: "The server issues a session token that is valid for seven days." },
      { label: "03", text: "The house opens with your own audit chain and your own privacy settings." },
    ],
  },
};

export default function Auth({ mode }: { mode: AuthMode }) {
  const copy = COPY[mode];
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The API redirects a failed sign-in back to /#/login?error=CODE.
  useEffect(() => {
    const query = window.location.hash.split("?")[1];
    if (!query) {
      return;
    }
    const code = new URLSearchParams(query).get("error");
    if (code) {
      setError(ERROR_COPY[code.toLowerCase()] ?? "Sign-in did not finish. Try again.");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void authApi
      .config()
      .then((value) => {
        if (!cancelled) {
          setConfig(value);
        }
      })
      .catch(() => {
        // A server without the config route is older. The button still works,
        // so leave the state alone and let the click report a real failure.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const startGoogle = () => {
    setBusy(true);
    setError(null);
    const path = config?.login_url ?? "/api/auth/google/start";
    const target = `${API_BASE}${path}?redirect_after=${encodeURIComponent("/demo")}`;
    window.location.href = target;
  };

  const disabled = busy || (config !== null && !config.enabled);

  return (
    <div className="lp lp-auth">
      <header className="lp-header">
        <div className="lp-container lp-header-inner">
          <a className="lp-brand" href="#/" aria-label="Alexa 3.5 home">
            <span className="lp-brand-mark" aria-hidden="true">
              ✳
            </span>
            <span>Alexa</span>
            <span className="lp-brand-version">3.5</span>
          </a>
          <div className="lp-header-actions">
            <a className="lp-quiet-link lp-hide-mobile" href="#/console">
              Under the hood
            </a>
            <a className="lp-back-link" href="#/">
              Back to landing
            </a>
          </div>
        </div>
      </header>

      <main className="lp-auth-main">
        <section className="lp-auth-card">
          <p className="lp-kicker">
            <span>{copy.eyebrow}</span>
            with a Google account
          </p>
          <h1>{copy.title}</h1>
          <p className="lp-auth-lede">{copy.lede}</p>

          <button
            className="lp-google-button"
            type="button"
            onClick={startGoogle}
            disabled={disabled}
          >
            <GoogleMark />
            {busy ? "Opening Google" : copy.button}
          </button>

          {config !== null && !config.enabled ? (
            <p className="lp-auth-error" role="alert">
              Google sign-in is not configured on this server.
              {config.missing && config.missing.length > 0 ? (
                <> The API is missing {config.missing.join(" and ")}. Set {config.missing.length === 1 ? "it" : "them"} on the API and restart it.</>
              ) : null}
              {" "}The development token still works in the operator console.
            </p>
          ) : null}

          {error ? (
            <p className="lp-auth-error" role="alert">
              {error}
            </p>
          ) : null}

          <p className="lp-auth-note">{copy.note}</p>

          <p className="lp-auth-switch">
            {copy.switchLine} <a href={copy.switchHref}>{copy.switchLink}</a>
          </p>
        </section>

        <aside className="lp-auth-aside">
          <p className="lp-mono-label">What happens next</p>
          <ol className="lp-auth-steps">
            {copy.steps.map((step) => (
              <li key={step.label}>
                <span>{step.label}</span>
                <p>{step.text}</p>
              </li>
            ))}
          </ol>
          <p className="lp-auth-aside-note">
            The demo house resets after inactivity or a redeploy. Your account and your sign-in stay.
          </p>
        </aside>
      </main>

      <footer className="lp-auth-footer">
        <p>© 2026 Alexa 3.5 demo. Not affiliated with Amazon.</p>
      </footer>
    </div>
  );
}
