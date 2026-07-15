# Session State — local RAG migration, answer-quality fixes, cleanup

> Working handoff so context survives a `/clear` or a new session. Created 2026-07-08.
> Branch: **`add-xml-and-activate-office-extractors`** (NOT merged to main yet — 15 commits ahead
> since the previous handoff below).
> Companion context: `README.md`, `OVERVIEW.md`, `SYSTEM-HANDOFF.md`, `ROADMAP.md` (all updated
> this session), and assistant memory (`local-rag-default`, `openwebui-embedder-english-only`,
> `docker-upgrade-wipes-kb`, `icloud-move-hang`).
>
> The previous handoff below this line (file-format support / .msg recovery / iCloud resilience)
> is **resolved and superseded** — kept for git-blame continuity only. Its OPEN ITEM (.msg
> attachment recovery) is done: 22 `source_email:` backlinks now exist in the vault.

## Why this session happened
Owner shared an external architecture review of `README.md` (Docling/PaddleOCR, dynamic project
classification, Open WebUI alternatives). Verified it against the actual code, found it partly
right/partly wrong, then executed the validated plan end-to-end, plus follow-on bug fixes the
owner caught by actually using the bot.

## What changed (all committed on the branch, oldest → newest)
1. **`a3a9f26`** — Fixed `watch.log` growing to **267GB**: `telegram_bot.py`'s `getUpdates` retry
   loop had no backoff, so a DNS hiccup made it spin instantly, writing a full traceback per
   iteration. Added exponential backoff (5s→60s) + `RotatingFileHandler` in `run_watch.py` so this
   class of bug can never fill the disk again.
2. **`854bbba`** — Found Open WebUI's RAG was silently embedding the Korean vault with
   **all-MiniLM-L6-v2 (English-only)**, not bge-m3 as README/skill assumed. Corrected docs.
3. **`13cf418`** — **Track 3: replaced Open WebUI/Docker RAG with local in-process RAG.** New
   `rag_local.py`: bge-m3 (via Ollama) embeddings into a file-based **LanceDB** index (`rag_db/`,
   gitignored). `telegram_bot.py` gained `RAG_BACKEND` (`local` default / `openwebui` fallback).
   `ingest_vault.py` gained `--backend local|openwebui`. Removes a whole failure class (Open WebUI
   silently going down; Docker upgrades previously wiped the KB — see `docker-upgrade-wipes-kb`
   memory) and fixes the Korean-recall problem from #2.
4. **`d4cab12`** — Auto-index: `pipeline.process_file` calls `rag_local.index_note()`
   (best-effort, non-fatal) right after writing a note. `watch.py` runs an hourly incremental
   full re-ingest backstop (`RAG_REINGEST_INTERVAL`) to catch notes made during a `pause_ai`
   window or hand-edited/renamed vault notes the watcher never sees.
5. **`28adfa7`** — **Track 1: dynamic project detection.** `classify.detect_project()` assigns
   `project` per work note from deterministic identifiers (lot numbers/addresses) instead of a
   single hardcoded default. Registry = `.env DEFAULT_WORK_PROJECT`/`PROJECT_IDENTIFIERS` +
   optional `WORK_PROJECTS` JSON for a 2nd+ project. `migrate_add_project.py` rewritten to
   re-derive `project` from each note's `source` filename (dry-run today = 0 changes, safe).
6. **`6b22d84`** — **Track 2: evaluated Docling/PaddleOCR/EasyOCR as Tesseract replacements —
   rejected.** EasyOCR fixed a header-doubling glitch but **misread lot-number digits**
   (685-317→685-377) — dangerous for this domain. PaddleOCR hit a paddle CPU backend bug on this
   Windows/Py3.13 box; Docling's transformers import crashed in an isolated venv (and its real
   value is native-PDF tables, not scan OCR anyway). Kept Tesseract. No production dependency
   changes; eval was done in throwaway venvs under the scratch temp dir.
7. **`af4affe`** — **Fixed 3 bugs that broke bot answers** (found by the owner testing live):
   - `num_ctx=8192` made `exaone3.5:7.8b` return 1-character replies in this Ollama build →
     reverted to the model's native 4096.
   - `chunk_text` never hard-split oversized paragraphs, so ungapped scan-OCR text became single
     4000+ char chunks; 8 of them (~33k chars) blew the context window and truncated away the
     answer. Now hard-splits at `CHUNK_CHARS=700`; vault re-chunked 520→2044 chunks.
   - One note could monopolize top-k, crowding out the note with the actual answer. Added
     `MAX_CHUNKS_PER_NOTE` + `CONTEXT_CHAR_BUDGET`. Citations now list only notes actually used.
8. **`a093c49`** — **Phase 8 answer grounding.** Each note's clean `## 요약` (written at
   classify-time) is stored (`summary` column) and prepended per-note at answer time — so facts
   (floor areas, dates, amounts) survive garbled scan OCR even when the raw chunk is noisy.
9. **`faf819d`** — **Phase 8 hybrid search.** `rag_local.search()` now does LanceDB hybrid
   retrieval (full-text + vector, RRF-fused; falls back to vector-only if no FTS index). Fixes
   ranking for lot-number/proper-noun queries the embedding alone blurred. Lowered answer
   generation `temperature` to 0.3 for factual consistency.
10. **`ed3c3e8`** — QoL: `pause_ai.bat`/`resume_ai.bat` double-click wrappers; richer bot
    `/start`/`/help` with concrete example questions.
11. **`4faeeb9`** — Brought `OVERVIEW.md`/`SYSTEM-HANDOFF.md` up to date (both still described
    Open WebUI/Docker as current; `SYSTEM-HANDOFF.md` even listed RAG as "not yet built").
12. **`049ecfe`** — Trimmed `bench_models.py`'s model list (referenced 2 now-deleted models).
13. Disk cleanup (not a commit — infra action): removed **~61GB** of unused Ollama models
    (`gemma4:26b` [the one that previously froze the PC by overflowing 16GB VRAM], `gemma4:e4b`,
    `codestral`, `qwen2.5:14b`, `mistral-nemo`, `qwen3.5`, `nomic-embed-text`) with owner's
    explicit approval. Kept `exaone3.5:7.8b`, `bge-m3`, `llama3.1` — the three the pipeline uses.

Interleaved ROADMAP-only commits (`f78165a`, `7e615b8`, `717e43d`, `6b22d84`, `730ffea`) recorded
each of the above as it landed — ROADMAP.md is current, treat it as authoritative for backlog.

## Current state (verified 2026-07-08, end of session)
- **Tests:** `uv run pytest -q` → **61 passed**.
- **Watcher process:** running, PID **86020**, started manually this session (`Start-Process
  pythonw.exe run_watch.py`) — **not** via the Scheduled Task, so `Get-ScheduledTask
  ArchivePipelineWatch` shows `Ready` (idle/registered) rather than `Running`; that's expected —
  the task only fires at boot. On next reboot it'll launch fresh and pick up all changes on this
  branch automatically (no action needed).
- **Ollama:** responding (200), 4 models loaded (see #13 above), VRAM ~8/16GB used.
- **RAG index:** `rag_db/` (LanceDB, ~20MB), 236 notes / ~2044 chunks, hybrid FTS+vector.
  `RAG_BACKEND` unset in `.env` → defaults to `local`.
- **Bot verified live** by the owner mid-session; multiple real Korean queries (permit dates,
  counterparties, floor areas, workout summaries) answered correctly with citations.
- **Untracked scratch files from an *earlier* (already-merged-in-spirit) session still sit in the
  repo root:** `_recover_msg.py`, `_retry_cycle.py`, `xmlextractorchanges.patch`. Not touched this
  session (out of scope); safe to delete once confirmed unneeded — they predate and are unrelated
  to this session's work (the patch was already applied back in commit `4e6267b`).

## Known remaining weak spot (not a bug — a small-model reasoning limit)
Asking for a *computed delta* like "증축 **후** 연면적" (floor area *after* expansion) sometimes
gets a hedge ("not explicitly stated") even though the permit's `연면적합계` value **is** in the
grounded context — `exaone3.5:7.8b` won't confidently equate "stated total" with "after" phrasing
100% of the time. Rephrasing more directly (e.g. "허가서 연면적 합계는?") gets a clean answer.
Not worth chasing further without a bigger model or a reranker (see ROADMAP Phase 8 — now marked
optional).

## Pending / optional next steps (see `ROADMAP.md` for full detail)
1. **Project-scoped RAG** — filter `rag_local` search by the `project` column once a 2nd project
   exists (`WORK_PROJECTS` in `.env`, then `migrate_add_project.py --execute`).
2. **Reranker** (cross-encoder) — only if hybrid search (already shipped) proves insufficient;
   adds a torch/transformers dependency weight, so treat as last resort.
3. **Docling for native-PDF tables** (내역서/견적서) — re-evaluate in a *clean* env (pin
   `transformers`, install outside a temp dir); never route Korean *scans* through a
   digit-misreading OCR engine (see item 6 above — EasyOCR/PaddleOCR both rejected for scans).
4. **Vault dedup cleanup** (~4 genuine duplicate notes) — destructive, needs owner review first.
5. **Merge to main** — branch is stable (61 tests, live-verified), 15 commits ahead. Ready for a
   PR whenever the owner wants to open one.
6. Delete the 3 leftover scratch files above, once confirmed unneeded.

## Quick resume checklist
- `git branch --show-current` → should be `add-xml-and-activate-office-extractors`.
- `uv run pytest -q` → 61 pass.
- `(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'").ProcessId` → watcher alive (or
  restart: `Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Stop-Process -Force`
  then `Start-Process .venv\Scripts\pythonw.exe run_watch.py`).
- Sanity-check RAG: `uv run python -c "import rag_local; print(rag_local.answer('685-317 도급계약 상대 회사는?'))"`
  should mention 영진건설/한스에이엔디.
- `/my-vault` in Claude Code for a guided health check + menu.
