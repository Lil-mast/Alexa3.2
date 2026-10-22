import type { ReactNode } from "react";

interface PageCopy {
  eyebrow: string;
  title: ReactNode;
  body: string;
}

const COPY: Record<string, PageCopy> = {
  demo: {
    eyebrow: "Demo",
    title: (
      <>
        The house is
        <br />
        <em>next.</em>
      </>
    ),
    body: "The protected simulation comes next in the build order. Lights, climate, timers, bookings, confirmations, and undo will all run through the real rules engine.",
  },
  account: {
    eyebrow: "Account",
    title: (
      <>
        Your session,
        <br />
        in one <em>place.</em>
      </>
    ),
    body: "The protected account page comes next in the build order. It will show the signed-in identity and the controls that belong to it.",
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
  body: "The landing page, the sign-in pages, and the callback are done. The rest of the routes are queued behind them.",
};

export default function ComingSoon({ path }: { path: string }) {
  const copy = COPY[path] ?? FALLBACK;

  return (
    <div className="lp lp-soon">
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
