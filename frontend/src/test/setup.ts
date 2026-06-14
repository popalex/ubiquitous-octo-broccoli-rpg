import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./server";

// Start MSW once for the whole run. Only error on *unhandled* /api calls so
// tests that stub `fetch` directly (api.test.ts, chat.test.ts) and incidental
// requests (e.g. telemetry) don't trip it.
beforeAll(() =>
  server.listen({
    onUnhandledRequest: (request, print) => {
      if (new URL(request.url).pathname.startsWith("/api")) print.error();
    },
  }),
);

// Unmount React trees and drop per-test request handlers between cases so the
// jsdom DOM and MSW state don't leak across tests.
afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => server.close());
