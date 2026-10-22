import type { ReactNode } from "react";

interface PageCopy {
  eyebrow: string;
  title: ReactNode;
  body: string;
}

const COPY: Record<string, PageCopy> = {
  signup: {
    eyebrow: "Sign up",
    title: (
      <>
        One Google tap,
        <br />
        then the <em>house.</em>
      </>
    ),
    body: "This page is next in the build order. It will carry the Google button and the privacy note, then hand the browser to the live house simulation.",
  },
  login: {
    eyebrow: "Log in",
    title: (
      <>
        Welcome
        <br />
        <em>back.</em>
      </>
    ),
    body: "This page is next in the build order. It will carry the Google button and a link to signup.",
  },
  demo: {
    eyebrow: "Demo",
    title: (
      <>
        The house is
        <br />
        <em>next.</em>
      </>
    ),
    body: "The protected simulation is next in the build order. Lights, climate, timers, bookings, confirmations, and undo will all run through the real rules engine.",
  },
  account: {
    eyebrow: "Account",
    title: (
      <>
        Your session,
        <br />
        <em>in one place.</em>
      </>
    ),
    body: "Demo house resets after inactivity or redeploy. Your account and sign-in stay.",
  },
  "auth/callback": {
    eyebrow: "Auth callback",
    title: (
      <>
        Exchanging
        <br />
        the <em>code.</em>
      </>
    ),
    body: "This route is next in the build order. It will read the one-time code from the hash, remove it with history.replaceState, exchange it for a session token, then route to the demo.",
  },
};

const FALLBACK: PageCopy = {
  eyebrow: "Not built yet",
  title: (
    <>
      This screen is
      <br />
      <em>next.</em>
    </>
  ),
  body: "The landing page is the first step of the build. The rest of the routes are queued behind it.",
};

export default function ComingSoon({ path }: { path: string }) {
  const copy = COPY[path] ?? FALLBACK;

  return (
    <div className="lp lp-soon">
      <header className="lp-header">
        <div className="lp-container lp-header-inner">
          <a className="lp-brand" href="#/" aria-label="Alexa home">
            <span className="lp-brand-mark" aria-hidden="true">
              ✳
            </span>
            <span>Alexa</span>
          </a>
          <div className="lp-header-actions">
            <a className="lp-quiet-link" href="#/console">
              Under the hood
            </a>
            <a className="lp-button lp-button-small" href="#/">
              Back to landing
            </a>
          </div>
        </div>
      </header>

      <main className="lp-container lp-soon-main">
        <p className="lp-kicker">
          <span>Next</span>
          {copy.eyebrow}
        </p>
        <h1>{copy.title}</h1>
        <p>{copy.body}</p>
        <div className="lp-soon-actions">
          <a className="lp-button lp-button-large" href="#/">
            Back to landing
          </a>
          <a className="lp-text-link" href="#/console">
            Look under the hood
          </a>
        </div>
      </main>
    </div>
  );
}
