import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles/theme.css";
import "./styles/app.css";
import "./styles/landing.css";
import "./styles/house.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Missing #root element in index.html");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
