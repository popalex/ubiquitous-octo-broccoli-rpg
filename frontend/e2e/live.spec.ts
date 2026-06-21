import { expect, test } from "./fixtures/test";

// Phase 2: full-stack contract test. Runs only against a real backend
// (docker-compose.e2e.yml) with E2E_MODE=live; the browser talks to FastAPI ↔
// Postgres for real, with the LLM faked server-side by the built-in `mock`
// provider (see app/providers/mock_provider.py). Skipped in the default
// route-interception mode, which smoke.spec.ts covers.
test.skip(process.env.E2E_MODE !== "live", "full-stack live mode only");

// A single linear journey, self-contained so it's safe against a shared DB and
// other parallel workers: it creates its own chronicle with a unique title and
// only ever touches that one. Asserts user-visible behavior only, so the same
// flows are validated as in mock mode — but through the real contract.
test("create → send → reply → delete round-trips through the real backend", async ({ page }) => {
  const title = `Live E2E ${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

  // ── create ────────────────────────────────────────────────────────────
  await page.goto("/chronicle/new");
  await page.getByLabel(/chronicle title/i).fill(title);
  // Load the default template ("Guide Rowan"), then begin the chronicle.
  await page.getByRole("button", { name: /summon character/i }).click();
  await expect(page.getByRole("status").filter({ hasText: /loaded/i })).toBeVisible();
  await page.getByRole("button", { name: /begin chronicle/i }).click();

  // Backend assigns a real (ULID) id — not the mock's sess-new-N.
  await page.waitForURL(/\/chronicle\/(?!new$)[^/]+$/);
  await expect(page.getByRole("region", { name: "Chat messages" })).toBeVisible();

  // ── send a turn → the mock provider streams a reply over real SSE ───────
  const composer = page.getByRole("textbox", { name: /write your response/i });
  await composer.fill("What do the blue lanterns mean?");
  await page.getByRole("button", { name: /send turn/i }).click();

  const log = page.getByRole("region", { name: "Chat messages" });
  await expect(log.getByText("What do the blue lanterns mean?")).toBeVisible();
  // The deterministic reply from app/providers/mock_provider.py, reassembled by
  // chat.ts from real streamed chunks.
  await expect(log.getByText(/glow blue tonight/i)).toBeVisible();

  // ── it persists: the new chronicle shows up in the hub ──────────────────
  await page.goto("/");
  const card = page.locator("article").filter({ hasText: title });
  await expect(card).toBeVisible();

  // ── delete it (UI confirms via window.confirm) ──────────────────────────
  page.once("dialog", (dialog) => dialog.accept());
  await card.getByRole("button", { name: /^delete$/i }).click();
  await expect(page.locator("article").filter({ hasText: title })).toHaveCount(0);
});
