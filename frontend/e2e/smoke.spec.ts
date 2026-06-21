import { expect, test } from "./fixtures/test";

// Phase 1: browser-faked /api, no backend. In live mode (Phase 2) these specs
// would hit the real API with hardcoded ids / pre-seeded state they can't
// create, so skip them — live.spec.ts covers the full stack instead.
test.skip(process.env.E2E_MODE === "live", "route-interception mode only");

test.describe("Chronicle Vault smoke", () => {
  test("lists existing chronicles in the hub", async ({ page, mock }) => {
    mock.seedSession({ id: "s1", title: "The First Tale" });
    mock.seedSession({ id: "s2", title: "The Second Tale" });

    await page.goto("/");

    await expect(page.getByRole("heading", { name: "The First Tale" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "The Second Tale" })).toBeVisible();
  });

  test("shows the empty-vault state when there are no chronicles", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/the vault is empty/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /open new chronicle/i })).toBeVisible();
  });

  test("creates a new chronicle and lands in its view", async ({ page }) => {
    await page.goto("/chronicle/new");

    // The default template ("Guide Rowan") seeds the form. Load it, then begin.
    await page.getByRole("button", { name: /summon character/i }).click();
    await expect(page.getByRole("status").filter({ hasText: /loaded/i })).toBeVisible();

    await page.getByRole("button", { name: /begin chronicle/i }).click();

    await page.waitForURL(/\/chronicle\/sess-new-\d+$/);
    await expect(page.getByRole("region", { name: "Chat messages" })).toBeVisible();
    // The summary bar reflects the freshly started chronicle.
    await expect(page.getByText("Rowan").first()).toBeVisible();
  });

  test("streams an in-character reply when a message is sent", async ({ page, mock }) => {
    mock.seedSession({ id: "send-1", gm_enabled: false });
    await page.goto("/chronicle/send-1");

    const composer = page.getByRole("textbox", { name: /write your response/i });
    await composer.fill("What do the blue lanterns mean?");
    await page.getByRole("button", { name: /send turn/i }).click();

    // The user's line, then the scripted SSE reply assembled by chat.ts from
    // its streamed chunks (getByText does a substring match).
    const log = page.getByRole("region", { name: "Chat messages" });
    await expect(log.getByText("What do the blue lanterns mean?")).toBeVisible();
    await expect(log.getByText("glow blue tonight")).toBeVisible();
  });

  test("renders the quest journal from the quests endpoint", async ({ page, mock }) => {
    mock.seedSession({ id: "quest-1", quests_enabled: true });
    await page.goto("/chronicle/quest-1");

    await expect(page.getByRole("heading", { name: /active arcs/i })).toBeVisible();
    await expect(page.getByText("The Blue Lanterns")).toBeVisible();
  });

  test("deletes a chronicle from the hub", async ({ page, mock }) => {
    mock.seedSession({ id: "doomed", title: "To Be Forgotten" });
    await page.goto("/");

    const card = page.getByRole("button", { name: /To Be Forgotten/ });
    await expect(card).toBeVisible();

    // The hub confirms via window.confirm before deleting.
    page.once("dialog", (dialog) => dialog.accept());
    await page
      .locator("article")
      .filter({ hasText: "To Be Forgotten" })
      .getByRole("button", { name: /^delete$/i })
      .click();

    await expect(page.getByText("To Be Forgotten")).toHaveCount(0);
    await expect(page.getByText(/the vault is empty/i)).toBeVisible();
  });
});
