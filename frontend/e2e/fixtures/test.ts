import { test as base } from "@playwright/test";

import { MockApi, type MockOptions } from "./mockApi";

/**
 * Test fixture that wires the browser-level API mock (Phase 1). Seed per-test
 * data before the first navigation:
 *
 *   test("…", async ({ page, mock }) => {
 *     mock.seedSession({ title: "X" });
 *     await page.goto("/");
 *   });
 *
 * In live mode (E2E_MODE=live, Phase 2) the mock is not installed — the same
 * specs run against a real backend. Seeding helpers are then a no-op at the
 * network layer; live-mode specs create data through the UI instead.
 */
type Fixtures = { mock: MockApi };

const isLive = process.env.E2E_MODE === "live";

export const test = base.extend<Fixtures>({
  // `auto: true` so interception is installed for every test, even ones that
  // don't reference `mock` directly (e.g. the empty-vault case).
  mock: [
    async ({ page }, use) => {
      const mock = new MockApi({} as MockOptions);
      if (!isLive) await mock.install(page);
      await use(mock);
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";
