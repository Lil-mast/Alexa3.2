import { useEffect, useState } from "react";

import ConsoleApp from "./ConsoleApp";
import ComingSoon from "./pages/ComingSoon";
import Landing from "./pages/Landing";

type Route =
  | { name: "landing" }
  | { name: "console" }
  | { name: "soon"; path: string };

/**
 * Hash routing, with one important distinction: section anchors such as
 * `#problem` belong to the landing page and must not be treated as routes.
 * Only hashes that start with `#/` change the screen.
 */
function readRoute(): Route {
  const hash = window.location.hash;
  // Bare anchors such as `#proof` belong to the landing page. A cold load of
  // one should render the landing page and scroll, not a placeholder route.
  if (hash && !hash.startsWith("#/")) {
    return { name: "landing" };
  }

  const raw = hash.replace(/^#\/?/, "");
  if (!raw || raw === "/") {
    return { name: "landing" };
  }
  if (raw === "console" || raw.startsWith("console/")) {
    return { name: "console" };
  }
  return { name: "soon", path: raw };
}

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute);

  useEffect(() => {
    document.title =
      route.name === "console"
        ? "Alexa Console — Under the hood"
        : route.name === "soon"
          ? "Alexa — Next in the build"
          : "Alexa — Your voice assistant should never guess";
  }, [route]);

  useEffect(() => {
    const onHash = () => {
      // A bare `#section` is an in-page anchor, not a route. Let the browser
      // scroll and leave the current screen mounted.
      if (window.location.hash && !window.location.hash.startsWith("#/")) {
        return;
      }
      const next = readRoute();
      setRoute(next);
      if (next.name !== "landing" || window.scrollY > 0) {
        window.scrollTo(0, 0);
      }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (route.name === "console") {
    return <ConsoleApp />;
  }
  if (route.name === "soon") {
    return <ComingSoon path={route.path} />;
  }
  return <Landing />;
}
