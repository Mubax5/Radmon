import React from "react";
import ReactDOM from "react-dom/client";
import "@cloudflare/kumo/styles/standalone";
import "./radmon.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
