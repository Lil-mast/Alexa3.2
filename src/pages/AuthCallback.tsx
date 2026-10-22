import { useEffect, useState } from "react";

import { AuthApiError, authApi } from "../api/auth";
import { writeSessionToken } from "../auth/session";

type State = "working" | "error";

const ERROR_COPY: Record<string, string> = {
  invalid_exchange_code: "That sign-in code has already been used. Start again.",
  account_not_found: "That account no longer exists.",
  auth_unavailable: "The sign-in service is not configured on this server yet.",
};

/**
 * The one-time code comes back in the hash, not in a query string, so it never
 * reaches a server log or a referrer header. It is removed from the address
 * bar before the exchange starts, then traded for a session token.
 */
export default function AuthCallback() {
  const [state, setState] = useState<State>("working");
  const [message, setMessage] = useState("Signing you in.");

  useEffect(() => {
    const hash = window.location.hash;
    const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
    const params = new URLSearchParams(query);
    const code = params.get("code") ?? "";
    const next = params.get("next") ?? "/demo";

    // Drop the code from the URL first. It is single use, and leaving it in
    // the address bar would let a screenshot or a shared link replay it.
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}#/auth/callback`,
    );

    if (!code) {
      setState("error");
      setMessage("This link is missing its sign-in code.");
      return;
    }

    void authApi
      .exchange(code)
      .then((session) => {
        writeSessionToken(session.token);
        const target = next.startsWith("/") ? next : "/demo";
        window.location.hash = `#${target}`;
      })
      .catch((error: unknown) => {
        setState("error");
        if (error instanceof AuthApiError) {
          setMessage(ERROR_COPY[error.code.toLowerCase()] ?? error.message);
          return;
        }
        setMessage("The sign-in could not be completed. Try again.");
      });
  }, []);

  return (
    <div className="lp lp-auth lp-callback">
      <header className="lp-header">
        <div className="lp-container lp-header-inner">
          <a className="lp-brand" href="#/" aria-label="Alexa 3.5 home">
            <span className="lp-brand-mark" aria-hidden="true">
              ✳
            </span>
            <span>Alexa</span>
            <span className="lp-brand-version">3.5</span>
          </a>
        </div>
      </header>

      <main className="lp-auth-main lp-callback-main">
        <section className="lp-auth-card">
          <p className="lp-kicker">
            <span>Callback</span>
            one-time code
          </p>
          {state === "working" ? (
            <>
              <h1>Signing you in.</h1>
              <p className="lp-auth-lede">
                The code is being exchanged for a session. The house opens when it lands.
              </p>
              <p className="lp-auth-status" role="status">
                <span className="lp-session-dot is-checking" />
                {message}
              </p>
            </>
          ) : (
            <>
              <h1>That did not go through.</h1>
              <p className="lp-auth-lede" role="alert">
                {message}
              </p>
              <p className="lp-auth-switch">
                <a href="#/login">Back to sign in</a>
              </p>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
