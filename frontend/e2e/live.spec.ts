import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures/test";

// Phase 2: full-stack contract test. Runs only against a real backend
// (docker-compose.e2e.yml) with E2E_MODE=live; the browser talks to FastAPI ↔
// Postgres for real, with the LLM faked server-side by the built-in `mock`
// provider (see app/providers/mock_provider.py). Skipped in the default
// route-interception mode, which smoke.spec.ts covers.
test.skip(process.env.E2E_MODE !== "live", "full-stack live mode only");

/** A unique title so each test owns its data on a shared, parallel-worker DB. */
const uniqueTitle = () => `Live E2E ${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

/** UI-driven create: load the default ("Guide Rowan") template, begin, land in
 *  the chronicle view. Returns once the chat region is ready. */
async function createChronicle(page: Page, title: string): Promise<void> {
  await page.goto("/chronicle/new");
  await page.getByLabel(/chronicle title/i).fill(title);
  await page.getByRole("button", { name: /summon character/i }).click();
  await expect(page.getByRole("status").filter({ hasText: /loaded/i })).toBeVisible();
  await page.getByRole("button", { name: /begin chronicle/i }).click();
  // Backend assigns a real (ULID) id — not the mock's sess-new-N.
  await page.waitForURL(/\/chronicle\/(?!new$)[^/]+$/);
  await expect(page.getByRole("region", { name: "Chat messages" })).toBeVisible();
}

/** Delete the chronicle with this title from the hub (confirm via window.confirm). */
async function deleteChronicle(page: Page, title: string): Promise<void> {
  await page.goto("/");
  const card = page.locator("article").filter({ hasText: title });
  await expect(card).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await card.getByRole("button", { name: /^delete$/i }).click();
  await expect(page.locator("article").filter({ hasText: title })).toHaveCount(0);
}

// A single linear journey, self-contained so it's safe against a shared DB and
// other parallel workers: it creates its own chronicle with a unique title and
// only ever touches that one. Asserts user-visible behavior only, so the same
// flows are validated as in mock mode — but through the real contract.
test("create → send → reply → delete round-trips through the real backend", async ({ page }) => {
  const title = uniqueTitle();
  await createChronicle(page, title);

  // ── send a turn → the mock provider streams a reply over real SSE ───────
  const composer = page.getByRole("textbox", { name: /write your response/i });
  await composer.fill("What do the blue lanterns mean?");
  await page.getByRole("button", { name: /send turn/i }).click();

  const log = page.getByRole("region", { name: "Chat messages" });
  await expect(log.getByText("What do the blue lanterns mean?")).toBeVisible();
  // The deterministic reply from app/providers/mock_provider.py, reassembled by
  // chat.ts from real streamed chunks.
  await expect(log.getByText(/glow blue tonight/i)).toBeVisible();

  // It persists, then clean up after ourselves.
  await deleteChronicle(page, title);
});

// The contract Phase 1 can't exercise: a turn's post-turn judge (the mock
// provider's canned world/quest deltas) must mutate the ledger and create a
// quest server-side, persist them, and the UI must refetch + render both. With
// the e2e stack's WORLD_STATE_ENABLED + QUESTS_ENABLED, a new chronicle
// inherits both features.
test("a turn creates a quest and mutates the ledger, and both render", async ({ page }) => {
  const title = uniqueTitle();
  await createChronicle(page, title);

  await page.getByRole("textbox", { name: /write your response/i }).fill("Tell me about the harbor.");
  await page.getByRole("button", { name: /send turn/i }).click();

  // Quest journal: the canned quest, created active by the judge, renders.
  // (The title also appears in "Quest started/taken up" notes — exact-match the
  // journal entry's <strong> to disambiguate.)
  await expect(page.getByText(/glow blue tonight/i)).toBeVisible();
  await expect(page.getByText("The Blue Lanterns", { exact: true })).toBeVisible();
  // Codex (world-state ledger): the canned NPC entity from the world delta.
  await expect(page.getByText("The Harbormaster", { exact: true })).toBeVisible();

  await deleteChronicle(page, title);
});
