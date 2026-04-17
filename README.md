# Small RPG GPT MVP

Hybrid roleplay chat backend built with FastAPI, PostgreSQL, pgvector, Alembic, and Docker Compose. It routes actor generation, memory extraction, summarization, embeddings, and continuity checks through configurable small-model providers only.

Default mode is Ollama-first and Docker Compose now runs Ollama inside the stack:

- Actor replies: Ollama (llama3.1:8b)
- Game Master (narration, events, NPCs): Ollama (llama3.1:8b)
- Memory extraction and summaries: Ollama (phi3:mini)
- Embeddings: Ollama (nomic-embed-text)
- OpenAI: optional fallback only

## Stack

- Python 3.11
- FastAPI
- SQLAlchemy 2.x
- Alembic
- PostgreSQL 16 + pgvector
- Docker Compose
- Ollama or OpenAI-compatible small models

## 1. Configure Environment

```bash
cp .env.sample .env
```

Defaults are already set up for Docker Compose to run Ollama locally in a container.

### Dev Mode (Single Model)

If you're low on RAM, enable dev mode to use a single smaller model for all LLM tasks:

```bash
DEV_MODE=true
DEV_MODEL_NAME=llama3.2:3b
```

This overrides actor, memory, and GM models to all use the same model.

### Production Mode (Multi-Model)

For best quality, use separate models optimized for each task:

- `ACTOR_MODEL_NAME=llama3.1:8b` - creative character dialogue
- `MEMORY_MODEL_NAME=phi3:mini` - precise fact extraction and summaries
- `GM_MODEL_NAME=llama3.1:8b` - world narration and events

Important:

- `OLLAMA_BASE_URL` should stay `http://ollama:11434` when the API runs inside Docker Compose.
- The first startup auto-pulls the configured models:
  - `llama3.1:8b` (actor + GM)
  - `phi3:mini` (memory)
  - `nomic-embed-text` (embeddings)
- In dev mode, only the single dev model + embeddings are pulled.

OpenAI is optional. If you want to switch providers later, set:

```bash
ACTOR_PROVIDER=openai
MEMORY_PROVIDER=openai
EMBEDDING_PROVIDER=openai
GM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
ACTOR_MODEL_NAME=gpt-4o-mini
MEMORY_MODEL_NAME=gpt-4o-mini
GM_MODEL_NAME=gpt-4o-mini
EMBEDDING_MODEL_NAME=text-embedding-3-small
EMBEDDING_DIMENSION=768
```

## 2. Start the Stack

```bash
docker compose up --build
```

This starts:

- `postgres` on `localhost:5432`
- `ollama` on `localhost:11434`
- `api` on `localhost:8000`
- `frontend` on `localhost:5173`

The startup flow is:

1. PostgreSQL starts
2. Ollama starts
3. `ollama-init` pulls the configured small models automatically
4. The API runs `alembic upgrade head`
5. Uvicorn starts
6. The `pnpm` frontend dev server starts

The first boot can take several minutes because model downloads happen automatically.

Open the UI at:

```bash
http://localhost:5173
```

If you want to run the frontend outside Docker:

```bash
cd frontend
pnpm install
pnpm dev
```

Then open:

```bash
http://localhost:5173
```

## 3. Run Migrations Manually

```bash
docker compose exec api alembic upgrade head
```

## 4. Seed a Default Character and World

```bash
docker compose exec api python -m app.seed
```

## 5. Health Check

```bash
curl http://localhost:8000/health
```

The browser UI uses the Vite dev proxy, so it talks to the backend through `/api/*` while you browse `localhost:5173`.

## 6. Load or Update a Character

```bash
curl -X POST http://localhost:8000/character/load \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Guide Rowan",
    "description": "A calm scout-mage who speaks in precise sensory detail and never breaks character.",
    "hard_rules": [
      "Stay in character as Rowan.",
      "Do not mention being an AI or a model.",
      "Respect established canon and prior facts."
    ],
    "style_guide": "Grounded fantasy, observant, concise.",
    "world_name": "Glass Harbor",
    "world_description": "A storm-lashed port city built around old mirrored ruins.",
    "world_canon": "A blue lantern warns of incoming tide spirits. The harbor gates close at moonrise.",
    "world_hard_rules": [
      "The setting remains low-magic and dangerous.",
      "No instant travel or modern technology."
    ]
  }'
```

## 7. Start a Session

Use the `character_card_id` and `world_state_id` returned from `/character/load`.

```bash
curl -X POST http://localhost:8000/session/init \
  -H "Content-Type: application/json" \
  -d '{
    "character_card_id": "CHARACTER_ID",
    "world_state_id": "WORLD_ID",
    "title": "Harbor opening scene"
  }'
```

## 8. Chat

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "SESSION_ID",
    "user_message": "Rowan, what do the blue lanterns mean tonight?"
  }'
```

## 9. Inspect Long-Term Memory

```bash
curl http://localhost:8000/session/SESSION_ID/memory
```

## Notes

- `MEMORY_SUMMARY_INTERVAL=6` means the system summarizes every 6 stored turns, which is 3 user/assistant exchanges.
- Hard rules are always included in the actor context packet.
- Retrieval ranking uses `score = 0.6 * semantic + 0.25 * recency + 0.15 * importance`.
- If first startup looks slow, check `docker compose logs -f ollama-init` to watch model pulls complete.
- If `/chat` returns a provider error, check `docker compose ps` and `docker compose logs ollama ollama-init api`.

## Game Master Mode

Enable GM mode when starting a session to get:

- **Scene narration** - atmospheric descriptions before/after character dialogue
- **Dynamic events** - random encounters, weather changes, NPC arrivals
- **NPC dialogue** - GM-controlled side characters
- **Scene transitions** - location and time changes with narrative bridges

GM mode settings:

```bash
GM_TEMPERATURE=0.8           # Higher for creative narration
GM_MAX_OUTPUT_TOKENS=800     # Longer for scene descriptions
EVENT_CHECK_INTERVAL=3       # Check for events every N turns
EVENT_PROBABILITY=0.4        # 40% chance when checked
```

The frontend UI has a GM toggle in the session setup form.
