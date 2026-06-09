import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import App from "./App";
import { ChronicleHub } from "./components/ChronicleHub";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { setupTelemetry } from "./telemetry";
import "./styles.css";

setupTelemetry();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ChronicleHub />} />
          <Route path="/chronicle/new" element={<App />} />
          <Route path="/chronicle/:sessionId" element={<App />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
);
