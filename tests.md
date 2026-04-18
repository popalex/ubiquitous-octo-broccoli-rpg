# Test Plan

## Current Coverage

### `test_continuity.py` — ContinuityService (DONE)
- [x] No issues returns draft unchanged
- [x] Issues present triggers revision
- [x] Whitespace revised falls back to draft
- [x] `applied=True` when revised differs from draft
- [x] ProviderError propagates
- [x] Empty/missing issues list in response

### `test_main.py` — API Integration (SKIPPED, needs rewrite)
- All tests skipped; marked as needing Postgres + pgvector harness

---

## Tests To Implement

### 1. `test_retrieval.py` — RetrievalService

Uses: `db_session`, `mock_provider` (embed_texts), factories  
Fixture: `RetrievalService(mock_provider)`

- [x] Returns empty list when no memories exist
- [x] Returns facts ranked by weighted score (semantic + recency + importance)
- [x] Returns episode summaries alongside facts
- [x] Respects `retrieval_top_k` setting (caps result count)
- [x] Recency scoring decays older memories
- [x] Importance score contributes to final ranking
- [x] Mixed facts and summaries are merged and re-sorted

### 2. `test_memory.py` — MemoryService

Uses: `db_session`, `mock_provider`, factories  
Fixture: `MemoryService(mock_provider, mock_provider)`

- [x] `maybe_refresh` is a no-op when turn count is below interval threshold
- [x] `maybe_refresh` creates an EpisodeSummary when threshold is met
- [x] `maybe_refresh` extracts and persists MemoryFact entries
- [x] `maybe_refresh` creates/updates RelationshipState entries
- [x] Embeddings are generated for new facts and summaries
- [x] `last_summarized_turn` on session is advanced after refresh
- [x] MemoryRefreshResult reports correct counts
- [x] Malformed LLM JSON for facts is handled gracefully
- [x] Malformed LLM JSON for episode summary is handled gracefully

### 3. `test_game_master.py` — GameMasterService

Uses: `db_session`, `mock_provider`, factories  
Fixture: `GameMasterService(mock_provider)`

- [x] `generate_narration` returns narration text
- [x] `generate_narration_stream` yields chunks
- [x] `check_for_event` returns `should_trigger=False` when interval not met
- [x] `check_for_event` returns a valid `EventCheckResult` when triggered
- [x] `generate_event` returns a `GeneratedEvent` with expected fields
- [x] `generate_scene_transition` returns narration, time_passed, and new elements
- [x] `generate_npc_dialogue` returns dialogue text
- [x] `analyze_world_state_changes` returns updates, flags_set, flags_cleared
- [x] ProviderError from LLM propagates through each method

### 4. `test_orchestrator.py` — OrchestratorService

Uses: `db_session`, `mock_provider`, factories  
Approach: patch sub-services or use MockProvider end-to-end

- [x] `chat` returns a ChatResponse with reply and continuity info
- [x] `chat` persists user turn and assistant turn in DB
- [x] `chat` triggers memory refresh when threshold is met
- [x] `chat` retrieves relevant memories and includes them in context
- [x] `chat` applies continuity correction when issues are found
- [x] `chat_stream` yields SSE chunks
- [x] `gm_chat` returns a GMChatResponse including narration
- [x] `gm_chat` triggers event generation when event check fires
- [x] `gm_chat` persists GM narration and event turns
- [x] `gm_chat_stream` yields SSE chunks
- [x] Missing session raises 404
- [x] Token budget is respected when building context

### 5. `test_providers.py` — Provider implementations

#### MockProvider (sanity)
- [x] `generate_text` returns configured response
- [x] `generate_json` returns configured dict
- [x] `embed_texts` returns vectors of correct dimension

#### OllamaProvider (unit, httpx mocked)
- [x] `generate_text` sends correct payload and parses response
- [x] `generate_text_stream` yields streamed chunks
- [x] `embed_texts` returns embeddings list
- [x] Connection error raises ProviderError

#### OpenAIProvider (unit, SDK mocked)
- [x] `generate_text` calls chat completions and returns content
- [x] `generate_text_stream` yields delta chunks
- [x] `embed_texts` calls embeddings endpoint
- [x] API error raises ProviderError

### 6. `test_api.py` — FastAPI endpoint integration

Uses: `async_client_mocked_orchestrator` (mocked LLM), `db_session`, factories

#### Health
- [x] `GET /health` returns 200 with `status: "ok"`

#### Character
- [x] `POST /character/load` creates character and world, returns IDs
- [x] `POST /character/load` upserts existing character by name
- [x] `POST /character/load` with missing required fields returns 422

#### Session
- [x] `POST /session/init` creates session linked to character and world
- [x] `POST /session/init` with `gm_enabled=True` sets GM fields
- [x] `POST /session/init` with invalid character_card_id returns 404/error

#### Chat
- [x] `POST /chat` returns reply, continuity info, retrieved memories
- [x] `POST /chat` with invalid session_id returns 404/error
- [x] `POST /chat/stream` returns SSE event stream

#### Memory
- [x] `GET /session/{id}/memory` returns facts, summaries, relationships
- [x] `GET /session/{id}/memory` for empty session returns empty lists

#### GM Endpoints
- [x] `POST /gm/chat` returns reply with narration and event info
- [x] `POST /gm/chat/stream` returns SSE event stream
- [x] `POST /gm/narration` returns narration text
- [x] `POST /gm/event/check` returns event check result
- [x] `POST /gm/event/generate` returns generated event
- [x] `POST /gm/scene/transition` returns transition narration
- [x] `POST /gm/npc/dialogue` returns NPC dialogue

### 7. `test_models.py` — ORM model tests

Uses: `db_session`, factories

- [x] CharacterCard round-trips through DB with all fields
- [x] WorldState round-trips through DB with all fields
- [x] Session cascades to turns on delete
- [x] Turn unique constraint on (session_id, turn_index)
- [x] MemoryFact stores and retrieves pgvector embedding
- [x] EpisodeSummary stores and retrieves pgvector embedding
- [x] RelationshipState links source/target entities correctly
- [x] TimestampMixin auto-sets created_at and updated_at

### 8. `test_factories.py` — Factory sanity checks

Uses: `db_session`

- [x] Each factory creates a valid, persisted row
- [x] SubFactory relationships are wired correctly (Session → CharacterCard, WorldState)
- [x] Sequence fields produce unique values across multiple creates
