# Session State — pipeline moves to n100 as a personal-use system (cloud classifier + cloud OCR)

> Working handoff so context survives a `/clear` or a new session. Created 2026-07-29.
> Branch: **`n100-cloud-backends`**. The previous session's branch (`add-xml-and-activate-office-extractors`) is
> merged (`b41b073`), plus three follow-on commits landed on main since: `58db357` (selectable
> Gemini backend for classifier), `7d7225e` (Gemini `thinking_level` fix), `ad5bb7e` (gitignore for
> local `vault/`/`.agents/`). That whole previous handoff (local RAG migration, answer-quality
> fixes, cleanup) is resolved and superseded — see git history if needed, not repeated here.
> Companion context: `README.md`, `OVERVIEW.md`, `SYSTEM-HANDOFF.md`, `ROADMAP.md` (all updated
> this session).

## Why this session happened
STRX-D75 (the RTX 4080 box that runs Ollama) was unavailable, but document extraction still needed
to run, so the pipeline was stood up on **n100-win** (hostname `NUCBOXG2`, an Intel N100 mini PC —
4 cores, 11.7GB RAM, integrated graphics, no Ollama, no Tesseract). A local LLM on that hardware
was measured and ruled out: a 4B-class model would take roughly 2 to 4 minutes per document there,
and small models drop fields on Korean structured JSON extraction, versus about 1.5 seconds via a
cloud API. So n100 runs the **same repo**, with the cloud backend selected purely through its own
machine-local `.env` (gitignored — no other machine's `.env` or behavior changes).

**Mid-session the scope changed, and this is now the standing plan (decided 2026-07-29):**
- **This repo is the owner's personal-use pipeline, and n100 is its permanent home** — not a
  temporary stand-in. STRX-D75 is no longer expected to run it.
- **Company/client material gets its own separate RAG on STRX-D75**, to be built later. That system
  is out of scope for this repo.
- Input stays the shared iCloud `_inbox` and notes stay in the existing `KC_second_brain` vault.
  The owner explicitly accepts that company documents they drop in for scheduling/study purposes
  will be sent to the cloud API by this pipeline. A separate company vault comes later.
- **The Telegram bot will run on n100 with cloud embeddings + cloud answers.** Not built yet; see
  "Pending" below. Note this means the whole vault, including existing `10_Professional` notes,
  gets embedded through the cloud API once — flagged to and accepted by the owner.

## What changed (uncommitted as of this session — see below)
1. **Classifier model pin.** `.env` on n100 uses `LLM_PROVIDER=gemini`,
   `GEMINI_MODEL=gemini-3.1-flash-lite` (the GA name; previously pinned to the preview build
   `gemini-3.1-flash-lite-preview`, which Google can retire without notice — GA behaves
   identically).
2. **Gemini 3.5 Flash Lite evaluated and REJECTED for the classifier.** A 10-run A/B at
   temperature 0 on the owner's real documents: `3.1-flash-lite` produced 10/10 identical titles;
   `3.5-flash-lite` produced 9/10, and twice emitted categories outside the controlled `DOC_TYPES`
   vocabulary (기록지, 기타), plus chose 체크리스트 for a training log. `category` becomes the note
   filename, so drift there fragments the vault. Pricing runs the same direction: 3.5 Flash Lite
   is $0.30 in / $2.50 out per 1M tokens vs $0.25 / $1.50 for 3.1 Flash Lite. Lesson: newer and
   pricier lost to older on a heavily tuned instruction-following prompt.
3. **Cloud OCR added to `extractors/extract.py`** (new capability, needed because n100 has no
   Tesseract): env-keyed OCR backend, `OCR_PROVIDER=tesseract` (default — STRX-D75 untouched) or
   `gemini`. The Gemini path renders PDF pages with PyMuPDF and sends them to a vision model for
   verbatim transcription, with **no binarization** (that preprocessing helps Tesseract but hurts
   vision models). Settings: `GEMINI_OCR_MODEL` (default `gemini-3.5-flash-lite`, chosen for its
   stronger vision evals, ~87.4% on OCR) and `GEMINI_OCR_MAX_PAGES` (default 30, a cost cap since
   each page is one API call). Verified on a synthetic Korean 대수선 허가필증 scan with no embedded
   text: every critical value transcribed exactly, including `685-317`, `성수동1가`, `1,247.85 ㎡`,
   `852,300,000`, `2018년 11월 29일`, `영진건설` — notable because ROADMAP already records EasyOCR
   misreading exactly these lot-number digits (`685-317` as `685-377`). The OCR call caps
   `max_output_tokens` and **raises on a truncated response** (`finish_reason=MAX_TOKENS`) rather
   than accepting a half-transcribed page as complete — silently changed values are this domain's
   worst failure. An OCR failure is **not** salvaged with leftover embedded text: by construction
   that text is already under the 50-char threshold, so falling back would classify a page number
   or watermark as the whole document. The exception propagates to `_failed` + Telegram instead.
   Finally, **embedded text with several distinct Private Use Area codepoints is treated as
   garbled and re-read via OCR.** A subset font with no `ToUnicode` table makes the extractor
   return raw glyph codes, which silently ate every number in the nutrition box and step list of a
   recipe PDF. Rendering the page and reading it visually sidesteps the font encoding entirely.
   The threshold counts *distinct* codepoints (`MIN_DISTINCT_PUA=5`) so a decorative divider that
   repeats one glyph 98 times — as the 영진 견적서 does — never triggers a needless full OCR.
4. **Bug fix in `pipeline._move_to`** (affects both machines — STRX-D75 gets it next pull).
   Archiving was silently stranding every file. Root cause: `os.rename` out of an iCloud-synced
   folder to a folder outside the sync root is intercepted by the Windows cloud filter driver,
   stalls 60 seconds, then fails with `WinError 426` (`ERROR_CLOUD_FILE_REQUEST_TIMEOUT`).
   `shutil.move`'s copy fallback only runs after that stall, but `_move_to`'s 20-second watchdog
   kills the worker first, so the file was retried forever every sweep. Fixed by using
   `shutil.copy2` + `os.unlink` and never attempting rename: same operation, 0.02 seconds. Full
   write-up: `learnings/2026-07-29-icloud-rename-winerror-426.md`.
5. **RAG turned off on this machine.** `.env` sets `RAG_BACKEND=off` because `rag_local.py`
   embeds with bge-m3 through Ollama, which can't run on the N100. Both call sites
   (`pipeline._index_note_best_effort` and `watch._reingest_rag_backstop`) already treat any
   non-`"local"` value as "skip", so no code change was needed for this.
6. **Autostart registered on n100.** Scheduled task `ArchivePipelineWatch` runs
   `.venv\Scripts\pythonw.exe run_watch.py` from the repo. Three deliberate differences from
   STRX-D75's task: trigger is **at logon, not at boot** (iCloud Drive is per-user; a session-0
   boot task only ever sees placeholders it can't hydrate), `ExecutionTimeLimit` is **unlimited**
   (the 3-day default would kill a long-running watcher), and `MultipleInstances IgnoreNew`
   prevents a second watcher stacking on the same inbox. Verified running against the live inbox;
   the Telegram bot skips itself (blank token) and the resource monitor degrades cleanly with no
   nvidia-smi and no Ollama present.

## Current state (verified 2026-07-29, end of session)
- **Verified end to end on n100:** two workout logs and one recipe PDF processed through the live
  watcher — classified in about 1.5s each, filed correctly, originals archived. Vault 267 → 270.
- **Tests:** 69 passing (was 61). The suite makes **no network calls**; verified by blanking
  `GEMINI_API_KEY` and re-running.
- **Cloud RAG and the Telegram bot are live on n100** (added 2026-07-30). `rag_local` gained the
  same env-keyed dispatcher treatment: `RAG_EMBED_PROVIDER` / `RAG_GEN_PROVIDER`, defaults still
  `ollama`. Indexed **251 notes / 2172 chunks in 165s** with `gemini-embedding-001` (3072-dim);
  answers come from `gemini-3.1-flash-lite` in 1.4–2.3s with correct citations. Only
  `95_Templates`, 3 root system notes and `91_임시메모` are outside `INCLUDE_DIRS`.
- **Three traps found by running it, all now guarded in code:** the embedding API rejects batches
  over 100; `gemini-embedding-2` silently returns one vector for many inputs; and an uncapped
  thinking budget made answers take 37–119s. See `ROADMAP.md` decision log.
- **`TELEGRAM_CHAT_ID` had been set to the bot's own id** (`8974535690` = @archive_pipeline_bot),
  so the bot read messages and answered nobody, and failure alerts went nowhere. Corrected to the
  owner's account (`300683554`, @dosaim).
- **Cosmetic, not fixed:** `send_message` sends plain text with no `parse_mode`, and Gemini emits
  far more markdown than EXAONE did, so `**bold**` shows up literally in Telegram.

## Pending / next steps
1. **Owner to confirm the bot answers from their phone.** Verified through the code path here, but
   the chat-id fix landed after their last attempt, so a real round trip is still unconfirmed.
2. **Optional: strip or convert markdown before sending to Telegram**, or set `parse_mode`. Cosmetic
   only — see the note above.
3. **Separate company RAG on STRX-D75** — planned, out of scope for this repo.
4. Everything previously listed in ROADMAP (project-scoped RAG, reranker, Docling for native-PDF
   tables, vault dedup cleanup) is unchanged by this session — see `ROADMAP.md` for full detail.

## Quick resume checklist
- `git branch --show-current` → `n100-cloud-backends` (or `main` once merged).
- On n100, confirm `.env` has `RAG_BACKEND=local`, `RAG_EMBED_PROVIDER=gemini`,
  `RAG_GEN_PROVIDER=gemini`, `RAG_EMBED_DIM=3072`, and a `TELEGRAM_CHAT_ID` that is the **owner's**
  account, not the bot's own id.
- On n100, confirm `.env` has `LLM_PROVIDER=gemini`, `GEMINI_MODEL=gemini-3.1-flash-lite`,
  `OCR_PROVIDER=gemini`, `RAG_BACKEND=off`. The backend switch is `.env` only — gitignored, so it
  never shows up in `git status`.
- `uv run pytest -q` → 69 pass.
- `uv run pytest -q` → 65 pass.
- On n100, `Get-ScheduledTask ArchivePipelineWatch` → `Running`. When STRX-D75 comes back, stop and
  disable it so only one machine watches the shared inbox.
- **After changing any pipeline code, restart the task** (`Stop-ScheduledTask` then
  `Start-ScheduledTask`). The watcher holds the code it imported at startup, so an edited file has
  no effect until then. This bit us once: a fix was verified green in tests while the live watcher
  quietly kept producing the broken output.
- `/my-vault` in Claude Code for a guided health check + menu.
