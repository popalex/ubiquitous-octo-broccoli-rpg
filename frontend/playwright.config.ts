import { defineConfig, devices } from "@playwright/test";

// Phase 1 (default): serve the real built frontend and fake every /api/** call
// in the browser (see e2e/fixtures/mockApi.ts) — no backend, no Postgres, no
// Ollama. Deterministic and offline.
//
// Phase 2 (future): set E2E_MODE=live and E2E_BASE_URL to a running full stack
// (frontend ↔ FastAPI ↔ Postgres, LLM faked at the backend). The fixture then
// skips browser route-interception and the same specs exercise the real API
// contract. Keep specs asserting only on user-visible behavior so both modes
// share them.
const PORT = 4173;
const isLive = process.env.E2E_MODE === "live";
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // In live mode the stack is started out-of-band; otherwise build + preview
  // the static frontend here.
  webServer: isLive
    ? undefined
    : {
        command: "pnpm build && pnpm preview",
        url: `http://127.0.0.1:${PORT}`,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
      },
});
