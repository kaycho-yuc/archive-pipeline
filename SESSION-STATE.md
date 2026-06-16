# Session State — file-format support, classifier model fix, iCloud resilience

> Working handoff so context survives a `/clear`. Created 2026-06-13, last verified 2026-06-16.
> Branch: **`add-xml-and-activate-office-extractors`** (NOT merged to main yet).
> Companion context: git log, `SYSTEM-HANDOFF.md`, `ROADMAP.md`, and assistant memory
> (`icloud-move-hang`, `docker-upgrade-wipes-kb`, `vault-schema-v2`).

## Why this work happened
A status check found ~44 files stuck in `_inbox` — they were core 성수동 685-317/383 project data
(`.xlsx` 내역서, `.msg` email trail, `.docx`, `.xml` 세금계산서) that the pipeline silently skipped.
Fixing that surfaced two more bugs. Then the drain itself kept freezing on iCloud-locked files.

## What was done (all committed on the branch)
1. **`4e6267b` — Activate xlsx/docx/msg extractors + add `.xml`.** Applied Ultraplan's
   `xmlextractorchanges.patch`. Root fix: `run_once.py`/`watch.py` had a stale local
   `SUPPORTED_EXTENSIONS` that dropped these types *before* extraction; now both import one set from
   `extractors/extract.py`. Added NTS e-tax-invoice (`.xml`) extractor with generic fallback.
2. **`88bae85` — Explode `.msg` attachments into their own notes with email provenance.**
   `extract.py:msg_attachments()` pulls each supported attachment; `pipeline.process_file` writes each
   back to `_inbox` and recursively processes it (own classified note), passing `origin_email` so
   `notes/write_note.py` records `source_email: "[[<email note>]]"` (Obsidian backlinks both ways).
   Skips `.p7s`/nested `.msg`.
3. **`916049b` — Load `.env` in `classify.py`.** It read `OLLAMA_MODEL` at import *before*
   `pipeline` called `load_dotenv()`, so the classifier silently fell back to **llama3.1** instead of
   the configured **exaone3.5:7.8b**. (The bot/RAG were always correct — different code path.) Now
   fixed; `DEFAULT_MODEL` resolves to exaone3.5:7.8b.
4. **`6bb6def` — Timeout-bounded file moves.** `shutil.move` hangs forever on a file iCloud is
   mid-syncing (copy succeeds, source *delete* blocks). `pipeline._move_to` now runs the move in a
   worker thread with `MOVE_TIMEOUT` (default 20s, `.env`-overridable); on timeout it logs
   `보류(이동지연)`, leaves the file, and continues — one stuck file can't freeze the pipeline. This
   was the root cause of every stall this session (and likely the earlier "PC froze"). See the
   `icloud-move-hang` memory.

All 37 tests pass (`uv run pytest -q`). uv is NOT on PATH — call `C:\Users\OWNER\.local\bin\uv.exe`.

## The iCloud blocker (environmental, not code)
The inbox files were iCloud cloud-backed placeholders (ReparsePoint set, Offline bit unset, so the
existing `_is_dehydrated` guard misses them). Verified: read/`copy2` work instantly, but `os.remove`
of the source hangs while iCloud syncs. Large unsupported uploads (`.pptx` 109MB + zips ~160MB) clog
iCloud's queue, holding the small `.msg`/`.xlsx` behind them. Resolves once iCloud finishes; the
move-timeout fix keeps the pipeline alive meanwhile.

## Current state (verified 2026-06-16)
- Watcher `ArchivePipelineWatch`: **Running** (bot + monitor + watch). Bot `@archive_pipeline_bot` online.
- `_inbox`: drained to only **unsupported** files (`alz`, `dwg`, `pptx`, 4×`zip`) plus a stray
  `.md` and a `.db` junk file. The `.xlsx/.docx/.msg/.xml` are gone from the inbox.
- Vault `10_Professional`: **198** work-notes (was 162). New exaone-classified notes exist
  (e.g. `2026-04-01 용역계약서 - 골든구스 코리아 … (최종)`).
- **OPEN ITEM — `.msg` attachments NOT captured:** `grep "source_email:"` across the vault = **0**,
  yet all **13 `.msg` are in `_archive`** (0 in inbox). So they were processed **body-only** (by old
  code / while iCloud-locked) and their attachments (contract scans, 내역서 that lived *inside* the
  emails) are still missing. **Recovery:** move the 13 `_archive/*.msg` back to `_inbox`, remove their
  entries from `processed_hashes.json` (so they aren't skipped as 중복), then `run_once` — the new
  code (commit 88bae85) explodes each attachment into its own note with `source_email` provenance.
  Confirm success by `grep -rl source_email …/10_Professional | wc -l` > 0.

## Auto-retry loop (scheduled 2026-06-13, may have lapsed over the 3-day gap)
Driver: `_retry_cycle.py` (+ `_autoretry_state.json`) — runs one drain cycle (lowers MOVE_TIMEOUT,
runs `run_once`), prints `CONTINUE remaining=N` / `DRAIN_DONE` / `DRAIN_STUCK`. A `ScheduleWakeup`
was set with a self-contained prompt: each wake-up run the cycle; while files remain, reschedule
(~1200s); when drained, run the **finishing steps** then stop. **If the wakeup lapsed (PC asleep),
re-arm it or just run the finishing steps manually.**

## Pending / how to finish (owner approved "re-revise all + re-ingest")
1. **Recover `.msg` attachments** (see OPEN ITEM above) — get them into the vault as notes.
2. **Re-revise ALL work notes with exaone** (now that the model is fixed):
   `uv run python migrate_revise_notes.py` (dry-run → builds `_revise_plan.json`) →
   `uv run python migrate_revise_notes.py --execute` (auto-backs up the vault zip).
3. **Re-ingest the KB** (clean rebuild per `docker-upgrade-wipes-kb` memory): warm bge-m3 →
   `POST /api/v1/knowledge/{KB}/reset` → `DELETE /api/v1/files/all` → `uv run python ingest_vault.py`.
   Verify via the bot chat path, not the raw retrieval endpoint.
4. **Clean up** temp files `_retry_cycle.py`, `_autoretry_state.json`; consider merging the branch
   `add-xml-and-activate-office-extractors` to main (PR or fast-forward) once verified.
5. Unsupported `.dwg`/`.pptx`(sample)/`.zip`/`.alz` remain out of scope.

## Quick resume checklist
- `git branch --show-current` → should be `add-xml-and-activate-office-extractors`.
- `uv run pytest -q` → 37 pass.
- `(Get-ScheduledTask ArchivePipelineWatch).State` → Running.
- Verify `.msg` attachment recovery, then do re-revise + re-ingest.
