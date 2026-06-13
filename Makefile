.PHONY: eval eval-verbose

# Run the on-demand LLM eval harness against a real local model (TODO §5a).
# Needs a reachable model — defaults to Ollama + DEV_MODEL_NAME on
# http://localhost:11434. Override with EVAL_MODEL / EVAL_PROVIDER /
# EVAL_JUDGE_MODEL / EVAL_OLLAMA_BASE_URL. Skips cleanly if unreachable.
eval:
	pytest -m eval

eval-verbose:
	pytest -m eval -v -s
