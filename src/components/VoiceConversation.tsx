import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api } from "../api/client";
import type { AssistantReply } from "../api/types";

type Turn = { id: number; role: "you" | "alexa"; text: string; status?: AssistantReply["status"] };
type VoiceState = "idle" | "listening" | "thinking" | "speaking" | "error";

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}

interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}

interface BrowserRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

type RecognitionConstructor = new () => BrowserRecognition;
type SpeechWindow = Window & {
  SpeechRecognition?: RecognitionConstructor;
  webkitSpeechRecognition?: RecognitionConstructor;
};

const STARTER_PROMPTS = ["Set a ten minute timer", "Turn on the kitchen lights", "Book a room tomorrow at 2 PM"];

export default function VoiceConversation() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [statusText, setStatusText] = useState("Ready when you are");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [voiceOutput, setVoiceOutput] = useState(true);
  const [handsFree, setHandsFree] = useState(false);
  const [recognitionAvailable, setRecognitionAvailable] = useState(false);
  const nextId = useRef(0);
  const recognition = useRef<BrowserRecognition | null>(null);
  const startListeningRef = useRef<() => void>(() => undefined);
  const audioUrl = useRef<string | null>(null);
  const feed = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const speechWindow = window as SpeechWindow;
    setRecognitionAvailable(Boolean(speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition));
    return () => {
      recognition.current?.stop();
      window.speechSynthesis?.cancel();
      if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
    };
  }, []);

  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  const addTurn = (turn: Omit<Turn, "id">) => {
    setTurns((previous) => [...previous, { ...turn, id: nextId.current++ }]);
  };

  const speak = async (text: string) => {
    const finishSpeech = () => {
      if (handsFree) {
        startListeningRef.current();
      } else {
        setVoiceState("idle");
        setStatusText("Ready when you are");
      }
    };
    if (!voiceOutput) {
      finishSpeech();
      return;
    }
    setVoiceState("speaking");
    setStatusText("Speaking");
    try {
      const clip = await api.speak(text);
      if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
      audioUrl.current = URL.createObjectURL(clip);
      const player = new Audio(audioUrl.current);
      player.onended = finishSpeech;
      player.onerror = () => speakInBrowser(text);
      await player.play();
    } catch {
      speakInBrowser(text);
    }
  };

  const speakInBrowser = (text: string) => {
    const finishSpeech = () => {
      if (handsFree) {
        startListeningRef.current();
      } else {
        setVoiceState("idle");
        setStatusText("Ready when you are");
      }
    };
    if (!window.speechSynthesis) {
      finishSpeech();
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onend = () => {
      finishSpeech();
    };
    utterance.onerror = () => {
      finishSpeech();
    };
    window.speechSynthesis.speak(utterance);
  };

  const submitTurn = async (utterance: string) => {
    const text = utterance.trim();
    if (!text || voiceState === "thinking") return;
    setErrorText(null);
    setDraft("");
    addTurn({ role: "you", text });
    setVoiceState("thinking");
    setStatusText("Thinking");
    try {
      const reply = await api.assistantTurn(text);
      addTurn({ role: "alexa", text: reply.speech, status: reply.status });
      await speak(reply.speech);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "I couldn't reach the assistant.";
      setErrorText(message);
      setVoiceState("error");
      setStatusText("Couldn't connect");
    }
  };

  const startListening = () => {
    const speechWindow = window as SpeechWindow;
    const Recognition = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    if (!Recognition || voiceState === "thinking" || voiceState === "listening") return;
    window.speechSynthesis?.cancel();
    const instance = new Recognition();
    recognition.current = instance;
    instance.lang = navigator.language || "en-US";
    instance.continuous = false;
    instance.interimResults = false;
    instance.onresult = (event) => {
      const result = event.results[event.resultIndex];
      if (result?.isFinal) void submitTurn(result[0].transcript);
    };
    instance.onerror = () => {
      setVoiceState("error");
      setStatusText("Didn't catch that");
      setErrorText("Check microphone permission, then try again or type your request.");
    };
    instance.onend = () => {
      setVoiceState((current) => current === "listening" ? "idle" : current);
      setStatusText((current) => current === "Listening" ? "Ready when you are" : current);
    };
    setErrorText(null);
    setVoiceState("listening");
    setStatusText("Listening");
    try {
      instance.start();
    } catch {
      setVoiceState("error");
      setStatusText("Microphone unavailable");
      setErrorText("Allow microphone access in your browser and try again.");
    }
  };

  startListeningRef.current = startListening;

  const stopListening = () => {
    recognition.current?.stop();
    setVoiceState("idle");
    setStatusText("Ready when you are");
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitTurn(draft);
  };

  const clearConversation = () => {
    recognition.current?.stop();
    window.speechSynthesis?.cancel();
    setTurns([]);
    setErrorText(null);
    setVoiceState("idle");
    setStatusText("Ready when you are");
  };

  return (
    <section className="talk-screen" aria-label="Talk to Alexa">
      <header className="talk-heading">
        <div>
          <p className="eyebrow">Voice assistant</p>
          <h1>Talk to Alexa</h1>
        </div>
        <button className="link-button" type="button" onClick={clearConversation} disabled={!turns.length}>
          Clear conversation
        </button>
      </header>

      <div className="conversation" aria-live="polite">
        {turns.length === 0 ? (
          <div className="talk-welcome">
            <div className={`voice-orbit ${voiceState === "listening" ? "is-listening" : ""}`} aria-hidden="true">
              <span className="voice-orbit-core">A</span>
            </div>
            <h2>What can I help with?</h2>
            <p>Try a home command. I’ll ask before completing actions that need confirmation.</p>
            <div className="suggestions">
              {STARTER_PROMPTS.map((prompt) => (
                <button key={prompt} className="suggestion" type="button" onClick={() => void submitTurn(prompt)}>
                  {prompt}<span aria-hidden="true">&#8599;</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="turn-list" ref={feed} aria-label="Conversation">
            {turns.map((turn) => (
              <li className={`turn turn-${turn.role}`} key={turn.id}>
                <span className="turn-speaker">{turn.role === "you" ? "You" : "Alexa"}</span>
                <p>{turn.text}</p>
                {turn.status === "confirmation_required" ? <span className="turn-note">Waiting for your yes or no</span> : null}
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="talk-controls">
        <div className="talk-status" role="status">
          <span className={`status-mark status-${voiceState}`} aria-hidden="true" />
          <span>{statusText}</span>
          {!recognitionAvailable ? <span className="status-hint">Voice input is not supported in this browser</span> : null}
        </div>
        {errorText ? <p className="talk-error" role="alert">{errorText}</p> : null}
        <form className="composer" onSubmit={onSubmit}>
          <button
            className={`mic-button ${voiceState === "listening" ? "is-listening" : ""}`}
            type="button"
            onClick={voiceState === "listening" ? stopListening : startListening}
            disabled={!recognitionAvailable || voiceState === "thinking"}
            aria-label={voiceState === "listening" ? "Stop listening" : "Start voice input"}
            title={voiceState === "listening" ? "Stop listening" : "Speak"}
          >
            <span className={voiceState === "listening" ? "mic-glyph mic-glyph-stop" : "mic-glyph"} aria-hidden="true" />
          </button>
          <input
            aria-label="Message Alexa"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask for something..."
            maxLength={500}
            disabled={voiceState === "thinking"}
          />
          <button className="send-button" type="submit" disabled={!draft.trim() || voiceState === "thinking"} aria-label="Send message" title="Send">
            &#8593;
          </button>
        </form>
        <label className="voice-toggle">
          <input type="checkbox" checked={voiceOutput} onChange={(event) => setVoiceOutput(event.target.checked)} />
          <span>Spoken replies</span>
        </label>
        {recognitionAvailable ? (
          <label className="voice-toggle hands-free-toggle">
            <input type="checkbox" checked={handsFree} onChange={(event) => setHandsFree(event.target.checked)} />
            <span>Keep listening after replies</span>
          </label>
        ) : null}
      </div>
    </section>
  );
}