import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api, readToken, writeToken } from "./api/client";
import type { Health, WhoAmI } from "./api/types";

const SCREENS = ["trace", "audit", "privacy", "journeys"] as const;
type Screen = (typeof SCREENS)[number];

const SCREEN_LABELS: Record<Screen, string> = {
  trace: "Trace",
  audit: "Audit",
  privacy: "Privacy",
  journeys: "Journeys",
};

const SCREEN_COPY: Record<Screen, { endpoint: string; body: string }> = {
  trace: {
    endpoint: "GET /api/trace?limit=50",
    body: "Every call Alexa+ made, newest first, with the decision, the latency, and the audit id. Polls only while the tab is visible.",
  },
  audit: {
    endpoint: "GET /api/audit and GET /api/audit/verify",
    body: "The hash chain, its current status, and the link between an action and the undo that reversed it.",
  },
  privacy: {
    endpoint: "privacy_get and privacy_set",
    body: "Five settings, enforced by the server. Every change is validated by the rules and written to the audit chain.",
  },
  journeys: {
    endpoint: "the terminal runner",
    body: "Run the YAML journeys and read pass or fail per step. The CLI stays the source of truth.",
  },
};

type Probe =
  | { state: "loading" }
  | { state: "ok"; health: Health }
  | { state: "error"; message: string };

function readScreen(): Screen {
  const value = window.location.hash.replace(/^#\/?/, "");
  return (SCREENS as readonly string[]).includes(value) ? (value as Screen) : "trace";
}

function describe(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

export default function App() {
  const [screen, setScreen] = useState<Screen>(readScreen);
  const [probe, setProbe] = useState<Probe>({ state: "loading" });
  const [savedToken, setSavedToken] = useState<string>(() => readToken());
  const [draft, setDraft] = useState<string>(() => readToken());
  const [identity, setIdentity] = useState<WhoAmI | null>(null);
  const [identityError, setIdentityError] = useState<string | null>(null);

  useEffect(() => {
    const onHash = () => setScreen(readScreen());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      setProbe({ state: "ok", health: await api.health() });
    } catch (error) {
      setProbe({ state: "error", message: describe(error) });
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void checkHealth();
      }
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [checkHealth]);

  useEffect(() => {
    let cancelled = false;
    if (!savedToken) {
      setIdentity(null);
      setIdentityError(null);
      return;
    }
    void api
      .whoami()
      .then((value) => {
        if (cancelled) {
          return;
        }
        setIdentity(value);
        setIdentityError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        setIdentity(null);
        setIdentityError(describe(error));
      });
    return () => {
      cancelled = true;
    };
  }, [savedToken]);

  const signIn = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = draft.trim();
    writeToken(next);
    setSavedToken(next);
  };

  const signOut = () => {
    writeToken("");
    setSavedToken("");
    setDraft("");
  };

  return (
    <div className="shell">
      <header className="app-header">
        <a className="brand" href="#/trace">
          Alexa <span>Console</span>
        </a>
        <nav className="nav" aria-label="Console sections">
          {SCREENS.map((item) => (
            <a
              key={item}
              className={item === screen ? "nav-link is-active" : "nav-link"}
              href={`#/${item}`}
              aria-current={item === screen ? "page" : undefined}
            >
              {SCREEN_LABELS[item]}
            </a>
          ))}
        </nav>
        <HealthPill probe={probe} />
      </header>

      {identity ? (
        <div className="identity">
          <span>
            signed in as <strong>{identity.subject}</strong>
          </span>
          <span className="identity-scopes">{identity.scopes.join(" ")}</span>
          <button className="link-button" type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      ) : (
        <form className="token-bar" onSubmit={signIn}>
          <label htmlFor="operator-token">Operator token</label>
          <input
            id="operator-token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="paste a bearer token"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button className="button" type="submit" disabled={!draft.trim()}>
            Use token
          </button>
          {identityError ? <span className="token-error">{identityError}</span> : null}
        </form>
      )}

      <main className="main">
        <section className="card">
          <p className="eyebrow">Scaffold only</p>
          <h1>{SCREEN_LABELS[screen]}</h1>
          <p>{SCREEN_COPY[screen].body}</p>
          <p>
            Reads <code className="code">{SCREEN_COPY[screen].endpoint}</code> when this screen is built.
          </p>
          <p className="note">
            The theme, the typed client, the shell, and the health probe are in place. The screens are
            the next step in <code className="code">FRONTEND.md</code>.
          </p>
        </section>
      </main>

      <footer className="footer">
        <span>
          {probe.state === "ok"
            ? `rules ${probe.health.rules_version} · server ${probe.health.version} · ${probe.health.audit_rows} audit rows`
            : "server status unknown"}
        </span>
        <a href="/docs">API docs</a>
      </footer>
    </div>
  );
}

function HealthPill({ probe }: { probe: Probe }) {
  if (probe.state === "loading") {
    return <span className="pill pill-loading">checking</span>;
  }
  if (probe.state === "error") {
    return (
      <span className="pill pill-danger" title={probe.message}>
        server unreachable
      </span>
    );
  }
  return (
    <span className="pill pill-ok" title={`${probe.health.service} ${probe.health.version}`}>
      {probe.health.tools} tools · {probe.health.audit_rows} rows
    </span>
  );
}
