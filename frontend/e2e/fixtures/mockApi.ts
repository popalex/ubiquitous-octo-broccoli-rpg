import type { Page, Route } from "@playwright/test";

/**
 * Browser-level fake of the FastAPI surface for Phase-1 E2E. A single
 * `page.route("**\/api/**")` catch-all answers every call from an in-memory
 * store, so the built frontend runs end-to-end with no backend, Postgres, or
 * Ollama. The chat reply is a scripted Server-Sent-Events body — the "LLM" is
 * just the strings in `reply` — so the real SSE parser in `chat.ts` runs
 * unchanged against canned output.
 *
 * Phase 2 will swap this for a real backend with the LLM faked server-side;
 * the specs stay because they assert only on what the user sees.
 */

type Flags = {
  gm_enabled: boolean;
  suggestions_enabled: boolean;
  world_state_enabled: boolean;
  quests_enabled: boolean;
};

type SessionRow = {
  id: string;
  title: string | null;
  status: string;
  turn_count: number;
  created_at: string;
  updated_at: string;
  character_card_id: string;
  world_state_id: string | null;
  character_name: string | null;
  world_name: string | null;
  current_location: string | null;
  time_of_day: string | null;
  summary: string | null;
  parent_session_id: string | null;
  forked_at_turn: number | null;
} & Flags;

type Quest = {
  id: string;
  slug: string;
  title: string;
  quest_type: string;
  description: string;
  stakes: string | null;
  status: string;
  origin: string;
  stages: { id: string; description: string; done: boolean }[];
  resolution: string | null;
  created_turn: number;
  accepted_turn: number | null;
  last_progress_turn: number;
  resolved_turn: number | null;
  created_at: string;
  updated_at: string;
};

const NOW = "2026-06-19T12:00:00Z";

const DEFAULT_FLAGS: Flags = {
  gm_enabled: false,
  suggestions_enabled: false,
  world_state_enabled: false,
  quests_enabled: true,
};

export function makeSession(overrides: Partial<SessionRow> = {}): SessionRow {
  return {
    id: "sess-seed",
    title: "A Seeded Tale",
    status: "active",
    turn_count: 4,
    created_at: NOW,
    updated_at: NOW,
    character_card_id: "cc-seed",
    world_state_id: "ws-seed",
    character_name: "Rowan",
    world_name: "Saltmarsh",
    current_location: null,
    time_of_day: null,
    summary: null,
    parent_session_id: null,
    forked_at_turn: null,
    ...DEFAULT_FLAGS,
    ...overrides,
  };
}

export function makeQuest(overrides: Partial<Quest> = {}): Quest {
  return {
    id: "q-seed",
    slug: "the-blue-lanterns",
    title: "The Blue Lanterns",
    quest_type: "mystery",
    description: "Discover why the harbor lanterns burn blue.",
    stakes: "The harbor's safety",
    status: "active",
    origin: "gm",
    stages: [{ id: "st1", description: "Question the harbormaster", done: false }],
    resolution: null,
    created_turn: 1,
    accepted_turn: 1,
    last_progress_turn: 2,
    resolved_turn: null,
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  };
}

export type MockOptions = {
  /** Sessions visible in the hub and openable by id. */
  sessions?: SessionRow[];
  /** Quests returned for any session's journal. */
  quests?: Quest[];
  /** Global feature defaults from /health (seed CodexSetup toggles). */
  health?: Partial<Flags>;
  /** Ordered chunk strings streamed as the assistant reply. */
  reply?: string[];
};

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export class MockApi {
  private sessions: SessionRow[];
  private quests: Quest[];
  private health: Flags;
  private reply: string[];
  private seq = 0;

  constructor(opts: MockOptions = {}) {
    this.sessions = opts.sessions ?? [];
    this.quests = opts.quests ?? [makeQuest()];
    this.health = { ...DEFAULT_FLAGS, ...opts.health };
    this.reply = opts.reply ?? ["The harbor lanterns ", "glow blue tonight."];
  }

  /** The full text the scripted reply accumulates to — handy for assertions. */
  get replyText(): string {
    return this.reply.join("");
  }

  seedSession(overrides: Partial<SessionRow> = {}): SessionRow {
    const row = makeSession(overrides);
    this.sessions.push(row);
    return row;
  }

  async install(page: Page): Promise<void> {
    await page.route("**/api/**", (route) => this.handle(route));
  }

  private handle(route: Route): Promise<void> | void {
    const req = route.request();
    const method = req.method();
    const path = new URL(req.url()).pathname.replace(/^\/api/, "");

    if (method === "GET" && path === "/health") {
      return json(route, { status: "ok", database: "ok", mode: "mock", ...this.health });
    }

    if (method === "GET" && path === "/sessions") {
      return json(route, { sessions: this.sessions });
    }

    if (method === "POST" && path === "/character/load") {
      const body = (req.postDataJSON() ?? {}) as { name?: string; world_name?: string };
      return json(route, {
        character_card_id: "cc-new",
        world_state_id: "ws-new",
        character_name: body.name ?? "Rowan",
        world_name: body.world_name ?? "Saltmarsh",
      });
    }

    // The chat stream lives at the top level (session id travels in the body),
    // not under /session/:id — both standard and GM paths.
    if (method === "POST" && (path === "/chat/stream" || path === "/gm/chat/stream")) {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: this.sseBody(),
      });
    }

    if (method === "POST" && path === "/session/init") {
      const body = (req.postDataJSON() ?? {}) as Partial<SessionRow> & {
        gm_enabled?: boolean | null;
        suggestions_enabled?: boolean | null;
        world_state_enabled?: boolean | null;
        quests_enabled?: boolean | null;
      };
      const id = `sess-new-${++this.seq}`;
      // null choice inherits the global default (mirrors the backend).
      const resolve = (v: boolean | null | undefined, g: boolean) => (v == null ? g : v);
      const row = makeSession({
        id,
        title: body.title ?? "Untitled Chronicle",
        turn_count: 0,
        character_card_id: body.character_card_id ?? "cc-new",
        world_state_id: body.world_state_id ?? "ws-new",
        character_name: "Rowan",
        world_name: "Saltmarsh",
        current_location: body.current_location ?? null,
        time_of_day: body.time_of_day ?? null,
        gm_enabled: resolve(body.gm_enabled, this.health.gm_enabled),
        suggestions_enabled: resolve(body.suggestions_enabled, this.health.suggestions_enabled),
        world_state_enabled: resolve(body.world_state_enabled, this.health.world_state_enabled),
        quests_enabled: resolve(body.quests_enabled, this.health.quests_enabled),
      });
      this.sessions.push(row);
      return json(route, {
        session_id: id,
        turn_count: 0,
        gm_enabled: row.gm_enabled,
        suggestions_enabled: row.suggestions_enabled,
        current_location: row.current_location,
        time_of_day: row.time_of_day,
        world_state_enabled: row.world_state_enabled,
        quests_enabled: row.quests_enabled,
      });
    }

    const sessionMatch = path.match(/^\/session\/([^/]+)(\/.*)?$/);
    if (sessionMatch) {
      const id = sessionMatch[1];
      const sub = sessionMatch[2] ?? "";
      const session = this.sessions.find((s) => s.id === id);

      if (method === "DELETE" && sub === "") {
        this.sessions = this.sessions.filter((s) => s.id !== id);
        return route.fulfill({ status: 204, body: "" });
      }
      if (method === "GET" && sub === "") {
        return session ? json(route, session) : json(route, { detail: "not found" }, 404);
      }
      if (method === "GET" && sub === "/turns") {
        return json(route, []);
      }
      if (method === "GET" && sub === "/memory") {
        return json(route, { session_id: id, facts: [], episode_summaries: [], relationships: [] });
      }
      if (method === "GET" && sub === "/world-state") {
        return json(route, { session_id: id, version: 0, created_at: null, state: {} });
      }
      if (method === "GET" && sub === "/quests") {
        return json(route, { session_id: id, quests: this.quests });
      }
      if (method === "GET" && sub === "/suggestions") {
        return json(route, { suggestions: [] });
      }
    }

    // Anything unmocked is a test bug — fail loudly rather than hang.
    return json(route, { detail: `unmocked: ${method} ${path}` }, 501);
  }

  /** A complete SSE body for /chat/stream: memories, the reply chunks, done. */
  private sseBody(): string {
    const frames: Record<string, unknown>[] = [
      { type: "memories", memories: [] },
      ...this.reply.map((content) => ({ type: "chunk", content })),
      { type: "done" },
    ];
    return frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
  }
}
