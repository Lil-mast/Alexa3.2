import { useEffect } from "react";
import type { ReactNode } from "react";

import HousePreview from "../components/landing/HousePreview";
import { useSessionDestination } from "../hooks/useSessionDestination";

interface SectionHeadProps {
  index: string;
  label: string;
  title: ReactNode;
  children?: ReactNode;
}

function SectionHead({ index, label, title, children }: SectionHeadProps) {
  return (
    <header className="lp-section-head">
      <p className="lp-kicker">
        <span>{index}</span>
        {label}
      </p>
      <div className="lp-section-head-grid">
        <h2>{title}</h2>
        {children ? <div className="lp-section-copy">{children}</div> : null}
      </div>
    </header>
  );
}

function Arrow({ size = 18 }: { size?: number }) {
  return (
    <svg
      className="lp-arrow"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M7 17 17 7" />
      <path d="M8 7h9v9" />
    </svg>
  );
}

function Check() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m4 10 4 4 8-8" />
    </svg>
  );
}

export default function Landing() {
  const session = useSessionDestination();

  useEffect(() => {
    // A cold load or a shared link may carry a bare section anchor. The
    // element does not exist until this component mounts, so scroll once here.
    const hash = window.location.hash;
    if (!hash || hash.startsWith("#/")) {
      return;
    }
    const target = document.getElementById(hash.slice(1));
    if (target) {
      requestAnimationFrame(() => target.scrollIntoView({ block: "start", behavior: "instant" }));
    }
  }, []);

  const sessionNote = session.checking
    ? "Checking your session"
    : session.destination === "house"
      ? "Session verified, the house is unlocked"
      : "A valid session opens the house directly";

  return (
    <div className="lp">
      <a className="lp-skip" href="#main">
        Skip to content
      </a>

      <header className="lp-header">
        <div className="lp-container lp-header-inner">
          <a className="lp-brand" href="#/" aria-label="Alexa 3.5 home">
            <span className="lp-brand-mark" aria-hidden="true">
              ✳
            </span>
            <span>Alexa</span>
            <span className="lp-brand-version">3.5</span>
          </a>

          <nav className="lp-nav" aria-label="Landing sections">
            <a href="#problem">Problem</a>
            <a href="#split">The split</a>
            <a href="#how">How it works</a>
            <a href="#proof">Proof</a>
            <a href="#faq">FAQ</a>
          </nav>

          <div className="lp-header-actions">
            <a className="lp-quiet-link" href="#/console">
              Under the hood <Arrow size={14} />
            </a>
            <a
              className="lp-button lp-button-small"
              href={session.href}
              onClick={session.open}
            >
              Try the house
              <Arrow size={15} />
            </a>
          </div>
        </div>
      </header>

      <main id="main">
        <section className="lp-hero" aria-labelledby="hero-title">
          <div className="lp-container lp-hero-grid">
            <div className="lp-hero-copy">
              <div className="lp-hero-meta">
                <p className="lp-kicker">
                  <span>01</span>
                  Introduction
                </p>
                <p className="lp-kicker lp-kicker-muted">Deterministic layer for Alexa+</p>
              </div>

              <h1 id="hero-title">
                Your voice assistant
                <br />
                should never <em>guess.</em>
              </h1>

              <p className="lp-lede">
                Alexa 3.5 turns what you say into exact actions. Rules decide, confirmations guard the
                risky ones, and a hash chain proves every move. The language model handles meaning,
                not your lights, climate, or calendar.
              </p>

              <div className="lp-hero-actions">
                <a
                  className="lp-button lp-button-large"
                  href={session.href}
                  onClick={session.open}
                >
                  {session.destination === "house" ? "Open the live house" : "Start with the house"}
                  <Arrow />
                </a>
                <a className="lp-text-link" href="#how">
                  See how it decides
                  <span className="lp-underline" />
                </a>
              </div>

              <p className="lp-session-note" aria-live="polite">
                <span
                  className={
                    session.checking
                      ? "lp-session-dot is-checking"
                      : session.destination === "house"
                        ? "lp-session-dot is-valid"
                        : "lp-session-dot is-anonymous"
                  }
                />
                {sessionNote}
              </p>

              <dl className="lp-hero-facts">
                <div>
                  <dt>Tools</dt>
                  <dd>8</dd>
                </div>
                <div>
                  <dt>Model-written state changes</dt>
                  <dd>0</dd>
                </div>
                <div>
                  <dt>Audited calls</dt>
                  <dd>100%</dd>
                </div>
              </dl>
            </div>

            <div className="lp-hero-visual">
              <div className="lp-visual-halo" aria-hidden="true" />
              <HousePreview />

              <div className="lp-float lp-float-chain">
                <span className="lp-chain-mark">
                  <Check />
                </span>
                <span>
                  <strong>Chain verified</strong>
                  <small>42 rows · head 28b292e4</small>
                </span>
              </div>

              <div className="lp-float lp-float-command">
                <span className="lp-mono-label">You</span>
                <p>“Dim the living room to thirty percent.”</p>
                <small>
                  <span className="lp-inline-dot" /> lights_set · 30 within 1 to 100 · 9 ms
                </small>
              </div>
            </div>
          </div>

          <div className="lp-marquee" aria-hidden="true">
            <div className="lp-marquee-track">
              {[0, 1].map((copy) => (
                <div className="lp-marquee-group" key={copy}>
                  {[
                    "Timers",
                    "Lights",
                    "Climate",
                    "Bookings",
                    "Confirmations",
                    "Undo",
                    "Audit",
                    "Privacy",
                  ].map((item) => (
                    <span key={item}>
                      {item}
                      <i>✳</i>
                    </span>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-section lp-problem" id="problem" aria-labelledby="problem-title">
          <div className="lp-container">
            <SectionHead
              index="02"
              label="The problem"
              title={
                <span id="problem-title">
                  Two ways a voice assistant
                  <br />
                  lets you <em>down.</em>
                </span>
              }
            >
              <p>
                One asks a model to do arithmetic. The other asks you to trust it. Neither is a
                system you can inspect when the answer is wrong.
              </p>
            </SectionHead>

            <div className="lp-problem-grid">
              <article className="lp-problem-card lp-problem-card-model">
                <div className="lp-card-topline">
                  <span>Case A, it improvises</span>
                  <span className="lp-card-number">01</span>
                </div>
                <h3>A timer is not a suggestion.</h3>
                <p>
                  When the model touches state directly, ten minutes becomes nine minutes and
                  fifty-eight seconds. A thermostat request becomes a number nobody approved.
                </p>
                <div className="lp-timer-art" aria-hidden="true">
                  <div>
                    <span className="lp-timer-label">You said</span>
                    <strong>10:00</strong>
                  </div>
                  <span className="lp-timer-arrow">→</span>
                  <div className="lp-timer-wrong">
                    <span className="lp-timer-label">It set</span>
                    <strong>09:58</strong>
                    <span className="lp-badge lp-badge-warn">Close enough?</span>
                  </div>
                </div>
              </article>

              <article className="lp-problem-card lp-problem-card-memory">
                <div className="lp-card-topline">
                  <span>Case B, it forgets</span>
                  <span className="lp-card-number">02</span>
                </div>
                <h3>A mistake with no receipt.</h3>
                <p>
                  No preview. No record. No undo. When a booking goes through twice or a light comes
                  on at 3 a.m., there is nothing to inspect and nobody to ask.
                </p>
                <div className="lp-receipt-art" aria-hidden="true">
                  <div className="lp-receipt-row">
                    <span>Booking confirmed</span>
                    <span>✓</span>
                  </div>
                  <div className="lp-receipt-row">
                    <span>Who approved it</span>
                    <span className="lp-missing">not logged</span>
                  </div>
                  <div className="lp-receipt-row">
                    <span>Audit row</span>
                    <span className="lp-missing">missing</span>
                  </div>
                  <div className="lp-receipt-row">
                    <span>Undo</span>
                    <span className="lp-missing">none</span>
                  </div>
                </div>
              </article>
            </div>

            <p className="lp-pull">
              A language model is excellent at <em>meaning.</em>
              <br />
              It is the wrong tool for <em>state.</em>
            </p>
          </div>
        </section>

        <section className="lp-split" id="split" aria-labelledby="split-title">
          <div className="lp-container">
            <SectionHead
              index="03"
              label="The split"
              title={
                <span id="split-title">
                  Alexa+ interprets.
                  <br />
                  Alexa 3.5 <em>decides.</em>
                </span>
              }
            >
              <p>
                Two jobs, two engines. Alexa+ owns the conversation and its interface. Alexa 3.5
                owns the deterministic execution underneath it.
              </p>
            </SectionHead>

            <div className="lp-table-wrap">
              <table className="lp-compare">
                <caption className="lp-sr-only">
                  Which layer owns each part of a voice request
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Job</th>
                    <th scope="col">
                      <span className="lp-col-name">Alexa+</span>
                      <span className="lp-col-note">Conversation</span>
                    </th>
                    <th scope="col">
                      <span className="lp-col-name">Alexa 3.5</span>
                      <span className="lp-col-note">Rules layer</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Understand the request", "Interprets", "not involved"],
                    ["Choose the action", "Suggests a tool", "Validates the call"],
                    ["Change device state", "Never", "Only through rules"],
                    ["Handle risk", "Shows the preview", "Issues a one-use token"],
                    ["Explain the outcome", "Renders the answer", "Writes the audit row"],
                    ["Reverse a mistake", "Asks to undo", "Runs the compensator"],
                  ].map(([job, plus, layer]) => (
                    <tr key={job}>
                      <th scope="row">{job}</th>
                      <td>{plus}</td>
                      <td>{layer}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="lp-statement">
              <span className="lp-statement-index">✳</span>
              <blockquote>
                The model never touches device state.
                <br />
                <em>That is the entire design.</em>
              </blockquote>
              <span className="lp-statement-meta">rules v1.0 / audit chain / five-minute tokens</span>
            </div>
          </div>
        </section>

        <section className="lp-section lp-how" id="how" aria-labelledby="how-title">
          <div className="lp-container">
            <SectionHead
              index="04"
              label="How it works"
              title={
                <span id="how-title">
                  Four steps.
                  <br />
                  <em>No improvising.</em>
                </span>
              }
            >
              <p>
                Every request follows the same path. It either ends in a deterministic action, a
                clarification, or a refusal with a reason.
              </p>
            </SectionHead>

            <ol className="lp-steps">
              {[
                {
                  number: "01",
                  tag: "Hear",
                  title: "Take the words, not the wheel",
                  copy: "Alexa+ passes the utterance. A deterministic parser extracts the tool and its values, or asks a question when the request is incomplete.",
                },
                {
                  number: "02",
                  tag: "Decide",
                  title: "Check before anything moves",
                  copy: "Scopes, bounds, privacy, and risk are checked first. A value outside 16 to 28 °C is refused with the range, not rounded into place.",
                },
                {
                  number: "03",
                  tag: "Confirm",
                  title: "Make risk a second step",
                  copy: "Medium and high risk return a preview and a single-use token that expires in five minutes. Nothing executes until you say yes.",
                },
                {
                  number: "04",
                  tag: "Prove",
                  title: "Leave a chain, not a story",
                  copy: "Every call becomes a hash-chained row. Reversible actions expose undo, linked to the action it reverses.",
                },
              ].map((step) => (
                <li className="lp-step" key={step.number}>
                  <div className="lp-step-rail">
                    <span className="lp-step-node" />
                  </div>
                  <div className="lp-step-head">
                    <span>{step.number}</span>
                    <span>{step.tag}</span>
                  </div>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                </li>
              ))}
            </ol>

            <div className="lp-trace">
              <div className="lp-trace-card">
                <div className="lp-trace-head">
                  <span className="lp-badge lp-badge-ok">
                    <Check /> Supported
                  </span>
                  <span className="lp-mono-label">Deterministic path</span>
                </div>
                <p className="lp-trace-say">“Dim the living room to thirty percent.”</p>
                <dl className="lp-trace-lines">
                  <div>
                    <dt>Rule</dt>
                    <dd>lights_set · brightness 30 · within 1 to 100</dd>
                  </div>
                  <div>
                    <dt>Do</dt>
                    <dd>living_room = 30%</dd>
                  </div>
                  <div>
                    <dt>Say</dt>
                    <dd>“Living room lights set to 30 percent.”</dd>
                  </div>
                </dl>
                <p className="lp-trace-foot">
                  executed · 9 ms · <span>a_000042</span>
                </p>
              </div>

              <div className="lp-trace-card lp-trace-card-quiet">
                <div className="lp-trace-head">
                  <span className="lp-badge lp-badge-clarify">?</span>
                  <span className="lp-mono-label">Clarification path</span>
                </div>
                <p className="lp-trace-say">“Make it cozy.”</p>
                <dl className="lp-trace-lines">
                  <div>
                    <dt>Rule</dt>
                    <dd>no supported intent</dd>
                  </div>
                  <div>
                    <dt>Do</dt>
                    <dd>nothing</dd>
                  </div>
                  <div>
                    <dt>Say</dt>
                    <dd>“Which room, and how warm would you like it?”</dd>
                  </div>
                </dl>
                <p className="lp-trace-foot">
                  clarification · 2 ms · <span>no state changed</span>
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="lp-section lp-proof" id="proof" aria-labelledby="proof-title">
          <div className="lp-container">
            <SectionHead
              index="05"
              label="Proof"
              title={
                <span id="proof-title">
                  The house is
                  <br />
                  the <em>argument.</em>
                </span>
              }
            >
              <p>
                No screenshots of a roadmap. The same server that answers the house writes the rows
                below. Open the console and read them yourself.
              </p>
            </SectionHead>

            <dl className="lp-stats">
              <div>
                <dt>Deterministic tools</dt>
                <dd>8</dd>
              </div>
              <div>
                <dt>Backend tests</dt>
                <dd>188</dd>
              </div>
              <div>
                <dt>Confirmation window</dt>
                <dd>
                  5<span>min</span>
                </dd>
              </div>
              <div>
                <dt>Calls audited</dt>
                <dd>100%</dd>
              </div>
            </dl>

            <div className="lp-proof-grid">
              <div className="lp-proof-panel">
                <div className="lp-panel-head">
                  <span className="lp-live">
                    <span className="lp-live-dot" />
                    Recent calls
                  </span>
                  <span className="lp-mono-label">newest first</span>
                </div>
                <ol className="lp-call-list">
                  <li>
                    <div className="lp-call-top">
                      <span className="lp-call-tool">lights_set</span>
                      <span className="lp-badge lp-badge-ok">executed</span>
                      <span className="lp-call-time">21:42:07</span>
                    </div>
                    <p>“Living room lights set to 30 percent.”</p>
                    <small>
                      9 ms · a_000042 · hash b37f805c…
                    </small>
                  </li>
                  <li>
                    <div className="lp-call-top">
                      <span className="lp-call-tool">thermostat_set</span>
                      <span className="lp-badge lp-badge-refused">refused</span>
                      <span className="lp-call-time">21:41:58</span>
                    </div>
                    <p>
                      “Temperature must be between 16 and 28 degrees. What would you like instead?”
                    </p>
                    <small>
                      OUT_OF_BOUNDS · a_000041 · no state changed
                    </small>
                  </li>
                  <li>
                    <div className="lp-call-top">
                      <span className="lp-call-tool">book_room</span>
                      <span className="lp-badge lp-badge-preview">previewed</span>
                      <span className="lp-call-time">21:41:12</span>
                    </div>
                    <p>“Book the Oak room on Friday at 9 AM. Should I go ahead?”</p>
                    <small>
                      confirmation_required · a_000040 · expires in 5:00
                    </small>
                  </li>
                </ol>
              </div>

              <aside className="lp-chain" aria-label="Audit chain status">
                <div className="lp-chain-status">
                  <span className="lp-chain-check">
                    <Check />
                  </span>
                  <div>
                    <span className="lp-mono-label">Audit chain</span>
                    <strong>Verified</strong>
                  </div>
                </div>
                <dl className="lp-chain-facts">
                  <div>
                    <dt>Rows</dt>
                    <dd>42</dd>
                  </div>
                  <div>
                    <dt>Head</dt>
                    <dd>28b292e4…</dd>
                  </div>
                  <div>
                    <dt>First bad</dt>
                    <dd>none</dd>
                  </div>
                </dl>
                <div className="lp-chain-row">
                  <span>a_000042</span>
                  <p>lights_set → executed</p>
                  <small>previous b37f805c…</small>
                </div>
                <p className="lp-chain-note">
                  Change one row and verification breaks. Retention keeps the chain link with a
                  tombstone.
                </p>
                <a className="lp-text-link" href="#/console">
                  Open the console
                  <Arrow size={15} />
                </a>
              </aside>
            </div>
          </div>
        </section>

        <section className="lp-privacy" id="privacy" aria-labelledby="privacy-title">
          <div className="lp-container lp-privacy-grid">
            <div className="lp-privacy-copy">
              <p className="lp-kicker">
                <span>06</span>
                Privacy
              </p>
              <h2 id="privacy-title">
                Settings that change behavior,
                <br />
                not just <em>copy.</em>
              </h2>
              <p>
                Every toggle is enforced by the server. Turning third-party sharing off refuses a
                room booking; changing retention replaces old rows with tombstones. The controls are
                not a promise layer.
              </p>
            </div>

            <div className="lp-privacy-list">
              {[
                {
                  name: "Third-party sharing",
                  state: "Off",
                  copy: "Room booking and cancellation are refused before any external call.",
                },
                {
                  name: "Personalization",
                  state: "On",
                  copy: "Preferences can inform a reply. Turning it off clears the stored detail history.",
                },
                {
                  name: "Listening",
                  state: "Declared",
                  copy: "Wake-word only. The device enforces it, not this server.",
                },
                {
                  name: "Keep details",
                  state: "30 days",
                  copy: "0 keeps no history. Expired rows become tombstones that preserve the chain.",
                },
              ].map((item) => (
                <div className="lp-privacy-item" key={item.name}>
                  <div className="lp-privacy-top">
                    <h3>{item.name}</h3>
                    <span>{item.state}</span>
                  </div>
                  <p>{item.copy}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-section lp-faq" id="faq" aria-labelledby="faq-title">
          <div className="lp-container lp-faq-grid">
            <div className="lp-faq-intro">
              <p className="lp-kicker">
                <span>07</span>
                FAQ
              </p>
              <h2 id="faq-title">
                Questions,
                <br />
                answered <em>directly.</em>
              </h2>
              <p>
                The short version: Alexa+ talks, Alexa executes, and the audit chain explains what
                happened.
              </p>
              <a className="lp-text-link" href="#/console">
                Inspect the operator view
                <Arrow size={15} />
              </a>
            </div>

            <div className="lp-faq-list">
              {[
                {
                  q: "Is Alexa 3.5 a replacement for Alexa+?",
                  a: "No. Alexa 3.5 is an MCP server and rules layer that Alexa+ calls. Alexa+ owns the conversation, the voice, and its own interface. Alexa owns the deterministic action underneath.",
                },
                {
                  q: "What happens when it doesn't understand?",
                  a: "It asks a clarification. It does not guess, run a partial action, or invent a device. An unknown phrase leaves the house exactly as it was.",
                },
                {
                  q: "Which actions need confirmation?",
                  a: "Medium and high risk actions. The preview names the service, the tool, the exact parameters, and the expected effect. A single-use token expires after five minutes, and nothing runs until it is presented.",
                },
                {
                  q: "Can I undo anything?",
                  a: "Reversible actions (lights, climate, timers, and bookings) expose a compensating action. The undo is its own audit row linked to the original. Irreversible actions are marked as such before confirmation.",
                },
                {
                  q: "What leaves the house?",
                  a: "Raw parameters stay out of the trace and audit rows; the server records a hash instead. Third-party sharing off refuses external bookings. Server text-to-speech is optional and honors the same settings.",
                },
                {
                  q: "Is the house real?",
                  a: "It is a simulation, but not a mock path. The adapters use the same rules engine, confirmation tokens, router, and audit chain as a real device adapter would. A restart clears in-memory state and the seeded audit fixture makes the reset visible.",
                },
                {
                  q: "How do I see the operator view?",
                  a: "Open Under the hood. The trace, audit, privacy, and journey screens use the same session token as the public app. The console renders decisions; it never makes them.",
                },
                {
                  q: "Do I need a microphone?",
                  a: "No. Voice input uses your browser's speech recognition when it is available, and every request can be typed. Server voice output is optional.",
                },
              ].map((item, index) => (
                <details className="lp-faq-item" key={item.q} open={index === 0}>
                  <summary>
                    <span>{item.q}</span>
                    <span className="lp-faq-plus" aria-hidden="true" />
                  </summary>
                  <p>{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-cta" aria-labelledby="cta-title">
          <div className="lp-container">
            <p className="lp-kicker">
              <span>08</span>
              Try it
            </p>
            <h2 id="cta-title">
              Ask for ten minutes.
              <br />
              Get <em>ten minutes.</em>
            </h2>
            <p className="lp-cta-copy">
              Set a timer, dim a room, push the thermostat out of range, book the Oak room, then ask
              for the undo. The house will do exactly what the rules allow, and show you why.
            </p>
            <div className="lp-cta-actions">
              <a
                className="lp-button lp-button-large lp-button-ink"
                href={session.href}
                onClick={session.open}
              >
                {session.destination === "house" ? "Open the live house" : "Start with the house"}
                <Arrow />
              </a>
              <a className="lp-text-link lp-text-link-light" href="#/console">
                Look under the hood
                <Arrow size={16} />
              </a>
            </div>
            <p className="lp-cta-note">{sessionNote}. Built for Alexa+ developers.</p>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-container">
          <div className="lp-footer-top">
            <a className="lp-brand lp-brand-footer" href="#/">
              <span className="lp-brand-mark" aria-hidden="true">
                ✳
              </span>
              <span>Alexa</span>
              <span className="lp-brand-version">3.5</span>
            </a>
            <nav className="lp-footer-nav" aria-label="Footer">
              <a href="#problem">Problem</a>
              <a href="#split">The split</a>
              <a href="#how">How it works</a>
              <a href="#proof">Proof</a>
              <a href="#faq">FAQ</a>
              <a href="#/console">Under the hood</a>
            </nav>
          </div>

          <div className="lp-footer-word" aria-hidden="true">
            ALEXA
          </div>

          <div className="lp-footer-bottom">
            <p>© 2026 Alexa 3.5. Not affiliated with Amazon. Alexa+ is a trademark of Amazon.</p>
            <p>
              Warm paper, deterministic rules, no dark mode. <a href="#/console">Operator view ↗</a>
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
