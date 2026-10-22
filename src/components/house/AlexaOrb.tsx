export type TalkPhase = "idle" | "listening" | "thinking" | "speaking";

const LABELS: Record<TalkPhase, string> = {
  idle: "Alexa is ready",
  listening: "Alexa is listening",
  thinking: "Alexa is working",
  speaking: "Alexa is speaking",
};

interface Props {
  phase: TalkPhase;
}

/**
 * The assistant's presence. Each phase has its own motion: a slow breath when
 * idle, ripples while listening, a turning ring while the rules decide, and a
 * short equaliser while speaking. Everything is CSS, so it costs no JavaScript
 * per frame.
 */
export default function AlexaOrb({ phase }: Props) {
  return (
    <div className={`hs-orb is-${phase}`} role="img" aria-label={LABELS[phase]}>
      <span className="hs-orb-ring hs-orb-ring-1" />
      <span className="hs-orb-ring hs-orb-ring-2" />
      <span className="hs-orb-ring hs-orb-ring-3" />
      <span className="hs-orb-core" />
      <span className="hs-orb-bars">
        <i />
        <i />
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}
