# Chronicle Hub — Main Page Implementation Plan

## Summary

Add a **Chronicle Hub** main page that lists existing chronicles (sessions) with brief summaries, and lets the user resume one or create a new chronicle. The current single-page app becomes the second view, shown after a chronicle is selected.

---

## Backend Changes

### 1. New API endpoint: `GET /sessions`
- Returns all sessions ordered by `updated_at DESC`
- Include: `id`, `title`, `status`, `gm_enabled`, `turn_count`, `created_at`, `updated_at`
- Include character name (join `CharacterCard.name`) and world name (join `WorldState.name`)
- Include a **brief summary**: the latest `EpisodeSummary.content` for that session, or fallback to the last assistant `Turn.content` (truncated to ~200 chars)
- Paginate if needed (optional v1 — sessions are unlikely to be >100)

### 2. New API endpoint: `GET /session/{session_id}/turns`
- Returns all `Turn` rows for the session, ordered by `turn_index ASC`
- Fields: `role`, `content`, `turn_type`, `turn_index`
- This is needed to **restore chat history** when resuming a chronicle

### 3. New API endpoint: `DELETE /session/{session_id}`
- Soft-delete: set `Session.status = "archived"`
- Optional but useful from day one to keep the list clean

---

## Frontend Changes

### 4. Install a client-side router
- Add `react-router-dom`
- Routes:
  - `/` → `<ChronicleHub />` (new main page)
  - `/chronicle/:sessionId` → existing app view (character + chat + memory panels)
  - `/chronicle/new` → existing app view in "new chronicle" mode (no session loaded)

### 5. New component: `<ChronicleHub />`
- Fetches `GET /sessions` on mount
- Renders a card grid/list of existing chronicles, each showing:
  - Title
  - Character name & world name
  - Turn count, GM mode badge
  - Last played date (`updated_at`)
  - Brief summary text (from the API)
- **"New Chronicle"** button → navigates to `/chronicle/new`
- Clicking an existing chronicle card → navigates to `/chronicle/:sessionId`

### 6. Update `<App />` to handle resume vs. new
- When navigated with a `sessionId` param:
  - Fetch `GET /session/{sessionId}/turns` to restore chat history
  - Fetch `GET /session/{sessionId}/memory` to restore memory panel
  - Load character/world data from the session (already available via session init response or a new endpoint)
- When navigated without a session (new mode):
  - Current behavior: show template picker, character form, "Begin Chronicle"
- After "Begin Chronicle" creates a session, update the URL to `/chronicle/:newSessionId`

### 7. Move state persistence from `localStorage` to URL
- `sessionId` comes from the route param instead of localStorage
- `characterCardId` and `worldStateId` can still use localStorage or be fetched from the session record
- Remove stale localStorage session recovery logic

---

## Task Checklist

- [ ] **BE-1** — Add `GET /sessions` endpoint (list chronicles with summary)
- [ ] **BE-2** — Add `GET /session/{id}/turns` endpoint (load chat history)
- [ ] **BE-3** — Add `DELETE /session/{id}` endpoint (archive chronicle)
- [ ] **FE-1** — Install `react-router-dom`, set up routes (`/`, `/chronicle/new`, `/chronicle/:sessionId`)
- [ ] **FE-2** — Build `<ChronicleHub />` component (chronicle list + new chronicle button)
- [ ] **FE-3** — Style the chronicle cards (title, character, summary, last played)
- [ ] **FE-4** — Update `<App />` to load existing session state when `sessionId` is in URL
- [ ] **FE-5** — Fetch and display turn history on chronicle resume
- [ ] **FE-6** — Navigate to `/chronicle/:id` after creating a new session
- [ ] **FE-7** — Clean up localStorage usage, rely on route params for session identity

---

## Open Questions / Future

- Pagination for the session list (defer unless >50 sessions expected)
- Search/filter chronicles by character or title
- Rename or edit chronicle title after creation
- "Continue where I left off" quick-resume button for the most recent chronicle
