import { useEffect, useState } from "react";

import type { HouseTimer } from "../../api/types";

interface Props {
  timers: HouseTimer[];
  /** When the timers were read, so the countdown can run between polls. */
  fetchedAt: number;
}

function formatRemaining(ms: number): string {
  const total = Math.ceil(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

export default function TimerList({ timers, fetchedAt }: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (timers.length === 0) {
    return <p className="hs-empty">No timers running.</p>;
  }

  return (
    <ul className="hs-list">
      {timers.map((timer) => {
        const remaining = Math.max(0, timer.remaining_s * 1000 - (now - fetchedAt));
        return (
          <li key={timer.id} className="hs-item">
            <span>{timer.label ?? "Timer"}</span>
            <strong>{formatRemaining(remaining)}</strong>
          </li>
        );
      })}
    </ul>
  );
}
