import { useCallback, useEffect, useState } from "react";
import type { MouseEvent } from "react";

import {
  checkSession,
  clearSessionToken,
  readSessionToken,
} from "../auth/session";

export type SessionDestination = "demo" | "signup";

export interface SessionRoute {
  /** Where the next plain click should go. */
  destination: SessionDestination;
  href: string;
  /** True while the stored token is being checked on first paint. */
  checking: boolean;
  /** Navigate after a fresh check, so a stale token never opens the demo. */
  open: (event: MouseEvent<HTMLAnchorElement>) => void;
}

/**
 * The landing page has one rule for its primary CTA: a valid session goes to
 * the demo, everything else goes to signup. The check runs on mount to label
 * the link, and again on click because a token can expire while a tab is open.
 */
export function useSessionDestination(): SessionRoute {
  const [destination, setDestination] = useState<SessionDestination>("signup");
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const token = readSessionToken();
    if (!token) {
      setDestination("signup");
      setChecking(false);
      return;
    }

    let cancelled = false;
    void checkSession(token).then((result) => {
      if (cancelled) {
        return;
      }
      if (result === "invalid") {
        clearSessionToken();
      }
      setDestination(result === "valid" ? "demo" : "signup");
      setChecking(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const open = useCallback((event: MouseEvent<HTMLAnchorElement>) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }

    event.preventDefault();
    const token = readSessionToken();
    if (!token) {
      window.location.hash = "#/signup";
      return;
    }

    setChecking(true);
    void checkSession(token).then((result) => {
      if (result === "invalid") {
        clearSessionToken();
      }
      const next = result === "valid" ? "#/demo" : "#/signup";
      setDestination(result === "valid" ? "demo" : "signup");
      setChecking(false);
      window.location.hash = next;
    });
  }, []);

  return {
    destination,
    href: destination === "demo" ? "#/demo" : "#/signup",
    checking,
    open,
  };
}
