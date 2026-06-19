import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

/**
 * A QueryClient tuned for tests: no retries (so a mocked error surfaces
 * immediately instead of being retried) and no caching across tests.
 */
export function makeTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

/** Render a tree wrapped in a fresh QueryClientProvider. */
export function renderWithClient(ui: ReactElement, client = makeTestQueryClient()) {
  const result = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { client, ...result };
}

/** A wrapper component for `renderHook`, carrying a shared client. */
export function createWrapper(client = makeTestQueryClient()) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { client, Wrapper };
}
