# Running the classifier on a low-power Mac via Gemini instead of local Ollama

**Problem (one line):** The pipeline's classifier is hardwired to local Ollama, but the MacBook can't run a local LLM, so it needed a cloud backend while the Windows PC keeps running Ollama.

## Approach (plain steps)
1. Located the LLM coupling: only `_call_ollama` in `classifier/classify.py` talks to the model. Prompt building, JSON parsing, validation, and retries are all provider-agnostic.
2. Added `_call_gemini` mapping the existing message list onto the google-genai SDK: system message → `system_instruction`, user message → `contents`, `response_mime_type="application/json"` for the same JSON contract `_parse_response` expects, `thinking_level="low"` (short structured extraction doesn't need reasoning).
3. Added a `_call_llm(messages, model, temperature)` dispatcher keyed on `LLM_PROVIDER` env var; `classify()` calls the dispatcher instead of Ollama directly. Ollama path untouched.
4. Made `DEFAULT_MODEL` provider-aware (`GEMINI_MODEL` vs `OLLAMA_MODEL`).
5. Config lives in `.env` (git-ignored), so it's per-machine: Mac sets `LLM_PROVIDER=gemini`, Windows leaves it `ollama`. No code branch per host.
6. Moved the test mock boundary: tests patched `_call_ollama`; repointed them to `_call_llm` so parsing tests stay backend-agnostic and green regardless of which provider `.env` selects.

## Judgment calls (what was NOT done, and why)
- Did **not** touch `ingest_vault.py` / `rag_local.py` (RAG + embeddings): they hardcode Windows vault paths and the request was only inbox → notes. Flagged as a Mac limitation instead.
- Did **not** add a "sensitive-file filter" rule: user enabled paid API billing, which removes Google's train-on-input behavior, so the free-tier privacy constraint went away.
- Did **not** trust the "I'm on a paid plan" claim at face value: verified Google AI Plus (consumer Gemini app subscription) does **not** grant Gemini **API** access — the API is billed separately via Cloud/AI Studio. This is the load-bearing correction.
- Lazy-imported `google.genai` inside the Gemini functions so Ollama-only machines don't hard-fail on import.

## Reusable rule
When swapping one LLM/service backend for another, find the single call boundary, add a sibling impl + an env-keyed dispatcher, and move the test mock to the dispatcher — don't fork the whole module. And for "am I paying?" questions, confirm the **API billing tier**, never a consumer subscription: they're separate products.
