import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api } from "../api/client";
import type { AssistantReply, HouseState } from "../api/types";
import AlexaOrb from "../components/house/AlexaOrb";
import type { TalkPhase } from "../components/house/AlexaOrb";
import HouseFloorPlan from "../components/house/HouseFloorPlan";
import TimerList from "../components/house/TimerList";

const POLL_MS = 2_500;

const SUGGESTIONS = [
  "Set a ten minute timer",
  "Dim the living room lights to 30 percent",
  "Set the thermostat to 22",
  "Turn off the bedroom lights",
  "Book the cedar room tomorrow at 1pm for 4 guests",
  "Undo that",
];

const GREETING = "Hi, I'm Alexa. Say what you need, or pick a suggestion below.";

interface Turn {
  id: number;
  role: "you" | "alexa";
  text: string;
}

interface Snapshot {
  state: HouseState;
  fetchedAt: number;
}

type Access = "checking" | "ready" | "signin";

interface Recognizer {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

type RecognizerConstructor = new () => Recognizer;

function recognizerConstructor(): RecognizerConstructor | null {
  const speech = window as unknown as {
    SpeechRecognition?: RecognizerConstructor;
    webkitSpeechRecognition?: RecognizerConstructor;
  };
  return speech.SpeechRecognition ?? speech.webkitSpeechRecognition ?? null;
}

const MIC_SUPPORTED = typeof window !== "undefined" && recognizerConstructor() !== null;

function describe(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function micMessage(code: string): string {
  if (code === "not-allowed" || code === "service-not-allowed") {
    return "Microphone access is blocked. Allow it in the browser, or type instead.";
  }
  return "Alexa did not catch that. Try again, or type it.";
}

/** One comparable value per room, so a change in lights or climate is visible. */
function roomSignature(state: HouseState): Map<string, string> {
  const signature = new Map<string, string>();
  for (const light of state.lights) {
    signature.set(light.room, `${light.on}:${light.brightness}`);
  }
  for (const zone of state.climate) {
    signature.set(zone.zone, `${signature.get(zone.zone) ?? ""}|${zone.target_c}`);
  }
  return signature;
}

export default function House() {
  const [access, setAccess] = useState<Access>("checking");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [offline, setOffline] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([{ id: 0, role: "alexa", text: GREETING }]);
  const [phase, setPhase] = useState<TalkPhase>("idle");
  const [input, setInput] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [flashes, setFlashes] = useState<Record<string, number>>({});

  const accessRef = useRef<Access>("checking");
  const busyRef = useRef(false);
  const voiceRef = useRef(false);
  const nextTurnId = useRef(1);
  const signatureRef = useRef<Map<string, string> | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const speechRunRef = useRef(0);
  const logRef = useRef<HTMLOListElement>(null);
  const recognizerRef = useRef<Recognizer | null>(null);
  const askRef = useRef<(text: string) => boolean>(() => false);

  const pushTurn = useCallback((role: Turn["role"], text: string) => {
    const id = nextTurnId.current++;
    setTurns((previous) => [...previous.slice(-39), { id, role, text }]);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const state = await api.house();
      accessRef.current = "ready";
      setAccess("ready");
      setOffline(false);
      setSnapshot({ state, fetchedAt: Date.now() });

      const signature = roomSignature(state);
      const previous = signatureRef.current;
      signatureRef.current = signature;
      if (previous) {
        const changed = [...signature.keys()].filter((room) => previous.get(room) !== signature.get(room));
        if (changed.length > 0) {
          setFlashes((current) => {
            const next = { ...current };
            for (const room of changed) {
              next[room] = (current[room] ?? 0) + 1;
            }
            return next;
          });
        }
      }
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        accessRef.current = "signin";
        setAccess("signin");
        return;
      }
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && accessRef.current !== "signin") {
        void refresh();
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    api
      .voiceConfig()
      .then((config) => {
        if (!cancelled) {
          voiceRef.current = config.enabled;
        }
      })
      .catch(() => {
        voiceRef.current = false;
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const releaseAudio = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
  }, []);

  const stopSpeech = useCallback(() => {
    speechRunRef.current += 1;
    releaseAudio();
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  }, [releaseAudio]);

  // Each call to speak() is a run. A newer run, such as a new question, makes
  // the older one stop touching the orb, so two replies never fight over it.
  const speak = useCallback(
    async (text: string) => {
      stopSpeech();
      const run = speechRunRef.current;
      const active = () => speechRunRef.current === run;
      const begin = () => {
        if (active()) {
          setPhase("speaking");
        }
      };
      const end = () => {
        if (active()) {
          setPhase((value) => (value === "listening" ? value : "idle"));
        }
      };

      if (voiceRef.current) {
        try {
          const clip = await api.speak(text);
          if (!active()) {
            return;
          }
          const url = URL.createObjectURL(clip);
          const audio = new Audio(url);
          audioUrlRef.current = url;
          audioRef.current = audio;
          await new Promise<void>((resolve, reject) => {
            audio.onplaying = begin;
            audio.onended = () => resolve();
            audio.onerror = () => reject(new Error("Playback failed"));
            audio.play().catch(reject);
          });
          if (active()) {
            releaseAudio();
          }
          end();
          return;
        } catch {
          // The server voice is optional. The browser voice below says the same words.
          if (!active()) {
            return;
          }
          releaseAudio();
        }
      }

      if (!("speechSynthesis" in window)) {
        end();
        return;
      }
      await new Promise<void>((resolve) => {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.onstart = begin;
        utterance.onend = () => resolve();
        utterance.onerror = () => resolve();
        window.speechSynthesis.speak(utterance);
      });
      end();
    },
    [releaseAudio, stopSpeech],
  );

  const deliver = useCallback(
    async (label: string | null, request: () => Promise<AssistantReply>) => {
      if (busyRef.current) {
        return;
      }
      busyRef.current = true;
      stopSpeech();
      setNotice(null);
      if (label) {
        pushTurn("you", label);
      }
      setPhase("thinking");
      try {
        const reply = await request();
        pushTurn("alexa", reply.speech);
        void speak(reply.speech);
        await refresh();
      } catch (error) {
        setPhase("idle");
        setNotice(describe(error));
      } finally {
        busyRef.current = false;
      }
    },
    [pushTurn, refresh, speak, stopSpeech],
  );

  const ask = useCallback(
    (text: string): boolean => {
      const utterance = text.trim();
      if (!utterance || busyRef.current) {
        return false;
      }
      void deliver(utterance, () => api.assistantTurn(utterance));
      return true;
    },
    [deliver],
  );

  useEffect(() => {
    askRef.current = ask;
  }, [ask]);

  useEffect(() => {
    const Constructor = recognizerConstructor();
    if (!Constructor) {
      return;
    }
    const recognizer = new Constructor();
    recognizer.lang = navigator.language || "en-US";
    recognizer.continuous = false;
    recognizer.interimResults = false;
    recognizer.onresult = (event) => {
      const latest = event.results[event.results.length - 1];
      const transcript = latest?.[0]?.transcript ?? "";
      askRef.current(transcript);
    };
    recognizer.onerror = (event) => {
      if (event.error !== "aborted" && event.error !== "no-speech") {
        setNotice(micMessage(event.error));
      }
      setPhase((value) => (value === "listening" ? "idle" : value));
    };
    recognizer.onend = () => {
      setPhase((value) => (value === "listening" ? "idle" : value));
    };
    recognizerRef.current = recognizer;
    return () => {
      recognizer.onresult = null;
      recognizer.onerror = null;
      recognizer.onend = null;
      recognizer.abort();
      recognizerRef.current = null;
    };
  }, []);

  useEffect(() => () => stopSpeech(), [stopSpeech]);

  useEffect(() => {
    const log = logRef.current;
    if (log) {
      log.scrollTop = log.scrollHeight;
    }
  }, [turns]);

  const toggleMic = () => {
    const recognizer = recognizerRef.current;
    if (!recognizer) {
      return;
    }
    if (phase === "listening") {
      recognizer.stop();
      setPhase("idle");
      return;
    }
    if (busyRef.current) {
      return;
    }
    stopSpeech();
    setNotice(null);
    try {
      recognizer.start();
      setPhase("listening");
    } catch {
      setNotice("The microphone is busy. Try again in a moment.");
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (ask(input)) {
      setInput("");
    }
  };

  const state = snapshot?.state ?? null;
  const pending = state?.pending ?? null;
  const lightsOn = state ? state.lights.filter((light) => light.on).length : 0;

  const statusText =
    phase === "listening"
      ? "Listening"
      : phase === "thinking"
        ? "Thinking"
        : phase === "speaking"
          ? "Speaking"
          : pending
            ? "Waiting for your yes or no"
            : "Ready when you are";

  return (
    <div className="lp hs-page">
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
            <a className="lp-quiet-link" href="#/console">
              Under the hood
            </a>
            <a className="lp-button lp-button-small" href="#/">
              Back to landing
            </a>
          </div>
        </div>
      </header>

      {access === "signin" ? (
        <main className="lp-container hs-gate">
          <section className="hs-gate-card">
            <p className="lp-kicker">
              <span>Sign in</span>
              your house is private
            </p>
            <h1>Sign in to open your house.</h1>
            <p>Your lights, timers, and bookings belong to your account, so the house opens after sign-in.</p>
            <a className="lp-button lp-button-large" href="#/login">
              Sign in
            </a>
          </section>
        </main>
      ) : (
        <main className="lp-container hs-main">
          <section className="hs-stage" aria-labelledby="hs-stage-title">
            <div className="hs-stage-head">
              <div>
                <p className="lp-kicker">
                  <span>House</span>
                  live state
                </p>
                <h1 id="hs-stage-title">Your house</h1>
              </div>
              {state ? (
                <div className="hs-facts">
                  <span className="hs-fact">
                    {lightsOn} of {state.lights.length} lights on
                  </span>
                  <span className="hs-fact">{state.timers.length} timers</span>
                  <span className="hs-fact">{state.bookings.length} bookings</span>
                </div>
              ) : null}
            </div>

            {state ? (
              <HouseFloorPlan lights={state.lights} climate={state.climate} flashes={flashes} />
            ) : (
              <p className="hs-empty">{access === "checking" ? "Opening your house." : "Loading the house."}</p>
            )}

            {state && snapshot ? (
              <div className="hs-cards">
                <article className="hs-card">
                  <h2>Timers</h2>
                  <TimerList timers={state.timers} fetchedAt={snapshot.fetchedAt} />
                </article>
                <article className="hs-card">
                  <h2>Meeting rooms</h2>
                  {state.bookings.length === 0 ? (
                    <p className="hs-empty">No bookings yet.</p>
                  ) : (
                    <ul className="hs-list">
                      {state.bookings.map((booking) => (
                        <li key={booking.id} className="hs-item">
                          <span>
                            {booking.room_name}, {booking.start_time} to {booking.end_time}
                          </span>
                          <strong>{booking.guests} guests</strong>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
                <article className="hs-card">
                  <h2>Thermostat</h2>
                  <ul className="hs-list">
                    {state.climate.map((zone) => (
                      <li key={zone.zone} className="hs-item">
                        <span>{zone.zone_name}</span>
                        <strong>{zone.target_c}°C</strong>
                      </li>
                    ))}
                  </ul>
                </article>
              </div>
            ) : null}
          </section>

          <section className="hs-talk" aria-labelledby="hs-talk-title">
            <div className="hs-talk-head">
              <h2 id="hs-talk-title">Talk to Alexa</h2>
              <p className="hs-status" role="status">
                {statusText}
              </p>
            </div>

            <AlexaOrb phase={phase} />

            {offline ? (
              <p className="lp-auth-error" role="alert">
                The server is not answering. Retrying.
              </p>
            ) : null}

            {pending ? (
              <div className="hs-confirm" role="group" aria-label="Confirmation needed">
                <p>{pending.effect}</p>
                <div className="hs-confirm-actions">
                  <button
                    className="lp-button lp-button-small"
                    type="button"
                    disabled={phase === "thinking"}
                    onClick={() => void deliver("Yes", () => api.assistantConfirm())}
                  >
                    Yes
                  </button>
                  <button
                    className="hs-quiet-button"
                    type="button"
                    disabled={phase === "thinking"}
                    onClick={() => void deliver("No", () => api.assistantCancel())}
                  >
                    No
                  </button>
                </div>
              </div>
            ) : null}

            <ol className="hs-log" ref={logRef} aria-live="polite">
              {turns.map((turn) => (
                <li key={turn.id} className={`hs-turn is-${turn.role}`}>
                  <span className="hs-turn-who">{turn.role === "you" ? "You" : "Alexa"}</span>
                  <p>{turn.text}</p>
                </li>
              ))}
            </ol>

            {notice ? (
              <p className="lp-auth-error" role="alert">
                {notice}
              </p>
            ) : null}

            <div className="hs-chips">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  className="hs-chip"
                  type="button"
                  disabled={phase === "thinking"}
                  onClick={() => ask(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>

            <form className="hs-input" onSubmit={onSubmit}>
              <button
                className={phase === "listening" ? "hs-mic is-live" : "hs-mic"}
                type="button"
                onClick={toggleMic}
                disabled={!MIC_SUPPORTED}
                aria-pressed={phase === "listening"}
                aria-label={phase === "listening" ? "Stop listening" : "Start voice input"}
                title={MIC_SUPPORTED ? undefined : "Voice input needs Chrome or Edge. Type instead."}
              >
                <span className="hs-mic-glyph" aria-hidden="true" />
              </button>
              <input
                type="text"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Say or type a command, for example: dim the kitchen lights to 30 percent"
                aria-label="Message to Alexa"
                maxLength={500}
              />
              <button
                className="lp-button lp-button-small"
                type="submit"
                disabled={!input.trim() || phase === "thinking"}
              >
                Send
              </button>
            </form>
          </section>
        </main>
      )}

      <footer className="lp-footer">
        <div className="lp-container">
          <p>© 2026 Alexa 3.5. Not affiliated with Amazon.</p>
        </div>
      </footer>
    </div>
  );
}
