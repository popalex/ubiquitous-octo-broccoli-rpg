import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import App from "./App";
import { ChronicleHub } from "./components/ChronicleHub";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { setupTelemetry } from "./telemetry";
import "./styles.css";

setupTelemetry();

const queryClient = new QueryClient({
  defaultOptions: {
    // Server reads here are session-scoped and refetched explicitly after
    // chat turns, so default to no automatic refetch-on-focus and one retry.
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<ChronicleHub />} />
            <Route path="/chronicle/new" element={<App />} />
            <Route path="/chronicle/:sessionId" element={<App />} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
