import { useEffect, useState } from "react";

import ConsoleApp from "./ConsoleApp";
import Auth from "./pages/Auth";
import AuthCallback from "./pages/AuthCallback";
import ComingSoon from "./pages/ComingSoon";
import Landing from "./pages/Landing";

type Route =
  | { name: "landing" }
  | { name: "console" }
  | { name: "signup" }
  | { name: "login" }
  | { name: "callback" }
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

  // The query lives inside the hash, for example
  // `#/auth/callback?code=...&next=/demo`. The route is the path in front of it.
  const raw = hash.replace(/^#\/?/, "");
  const path = raw.split("?")[0].replace(/\/+$/, "");

  switch (path) {
    case "":
      return { name: "landing" };
    case "console":
      return { name: "console" };
    case "signup":
      return { name: "signup" };
    case "login":
      return { name: "login" };
    case "auth/callback":
      return { name: "callback" };
    default:
      // The console keeps its own sub-screens, for example #/console/audit.
      return path.startsWith("console/") ? { name: "console" } : { name: "soon", path };
  }
}

const TITLES: Record<Route["name"], string> = {
  landing: "Alexa 3.5, your voice assistant should never guess",
  console: "Alexa 3.5 Console, under the hood",
  signup: "Sign up, Alexa 3.5",
  login: "Log in, Alexa 3.5",
  callback: "Signing you in, Alexa 3.5",
  soon: "Alexa 3.5, next in the build",
};

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute);

  useEffect(() => {
    document.title = TITLES[route.name];
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

  switch (route.name) {
    case "console":
      return <ConsoleApp />;
    case "signup":
      return <Auth mode="signup" />;
    case "login":
      return <Auth mode="login" />;
    case "callback":
      return <AuthCallback />;
    case "soon":
      return <ComingSoon path={route.path} />;
    default:
      return <Landing />;
  }
}
