# Session State — why this system is shaped the way it is

> Rewritten 2026-08-08. This file holds the **standing decisions and the reasoning behind them**,
> so a new session can act without re-deriving them. For what is running right now, see
> `STATUS.md`. For the decision log and backlog, `ROADMAP.md`. For solved problems and how,
> `learnings/`. The 2026-07-29 version of this file (the n100 migration handoff) is fully
> superseded; its content lives in git history and in the learnings notes cited below.

## The standing plan (decided 2026-07-29, unchanged)

- **This repo is the owner's personal-use pipeline, and n100-win is its permanent home.** Not a
  stand-in for STRX-D75. STRX-D75 is not expected to run it again.
- **Company/client material gets its own separate RAG on STRX-D75**, to be built later. Out of
  scope here. Refer to that machine by name, never as "the main PC".
- Input stays the shared iCloud `_inbox`; notes stay in the existing `KC_second_brain` vault.
- **Cloud exposure is accepted, explicitly.** Documents the owner drops in are sent to the Gemini
  API for classification, OCR, and embedding — including work documents dropped in for scheduling
  or study. The separate company vault is the answer to that, later.
- **If the vault is ever exposed on the web, only personal notes go.** This is now enforceable in
  the index: `domain` is a real column with 0% missing values across all notes.

## Why the engine is cloud, not local

n100-win is an Intel N100 mini PC — 4 cores, 11.7GB RAM, integrated graphics, no Ollama, no
Tesseract. A local LLM was measured and ruled out: a 4B-class model runs roughly 2 to 4 minutes per
document there and drops fields on Korean structured-JSON extraction, against about 1.5 seconds via
a cloud API. Every backend is selected through this machine's own gitignored `.env`, so no other
machine's behavior changes and the switch never shows up in `git status`.

## Model choices, and what lost

- **Classifier: `gemini-3.1-flash-lite`.** A 10-run A/B at temperature 0 on real documents:
  3.1 gave 10/10 identical titles; **3.5 gave 9/10 and twice invented categories outside the
  controlled `DOC_TYPES` vocabulary**. `category` becomes the note filename, so drift there
  fragments the vault. 3.5 also costs more ($0.30/$2.50 vs $0.25/$1.50 per 1M). Newer and pricier
  lost to older on a heavily tuned instruction-following prompt.
- **OCR: `gemini-3.5-flash-lite`.** Chosen separately from the classifier because transcription is
  a vision task. Pages are rendered with PyMuPDF and sent **without binarization** — that
  preprocessing helps Tesseract and hurts vision models.
- **Embeddings: `gemini-embedding-001`, 3072-dim. Qwen `text-embedding-v4` was evaluated and
  rejected** — it lost on date-scoped retrieval. Qwen generation actually won, but splitting the
  two providers was not worth the second failure surface. The dispatcher code stays, so reviving it
  is one `.env` edit plus a `--reset` re-index. See
  `learnings/2026-07-31-qwen-embedding-swap-gate-failure.md`.

## Rules this system learned the hard way

Each of these exists because the obvious version failed in production.

1. **Never `os.rename` out of the iCloud sync root.** The Windows cloud filter driver intercepts
   it, stalls 60 seconds, then fails with WinError 426 — and the 20s watchdog kills the worker
   first, so files were silently stranded and retried forever. Archiving now copies to `.part`,
   `os.replace`s into position, then unlinks the source.
   (`learnings/2026-07-29-icloud-rename-winerror-426.md`)
2. **An OCR failure is never salvaged with leftover embedded text.** By construction that text is
   already under the 50-char threshold, so falling back would classify a page number as the whole
   document. A truncated response (`finish_reason=MAX_TOKENS`) raises rather than passing as
   complete — silently changed values are this domain's worst failure.
3. **Embedded text with 5+ *distinct* Private Use Area codepoints is treated as garbled and
   re-OCR'd.** A subset font with no `ToUnicode` table returns raw glyph codes, which once ate
   every number in a recipe's nutrition box. Counting *distinct* codepoints keeps a decorative
   divider that repeats one glyph 98 times from triggering a needless full-document OCR.
   (`learnings/2026-07-29-pdf-font-subset-pua-digits.md`)
4. **The pipeline does not guess a project.** When it cannot identify one it writes
   `project: 미정` and pings Telegram for a human to settle it. A field can be 0% missing and still
   31% wrong. (`learnings/2026-08-02-silent-default-fakes-metadata-completeness.md`)
5. **Verify the risky mechanism before paying for a schema migration.** Before adding the filter
   columns, the open question was whether LanceDB's `.where()` binds to both halves of hybrid
   search or only the vector side — if only one, RRF would merge unfiltered FTS rows and leak work
   notes under `domain='개인'`. Tested first, migrated second.
   (`learnings/2026-08-02-verify-filter-before-schema-migration.md`)
6. **Back up a Lance dataset only when the index is quiet.** A `cp -r` during ingest yields a torn
   copy. (`learnings/2026-07-31-torn-lancedb-backup-mid-ingest.md`)
7. **Restart the scheduled task after any code change.** The watcher holds the code it imported at
   startup. A fix once sat green in tests while the live watcher kept emitting the broken output.

## Design constraints worth keeping

- **The MCP server must not make idle sessions pay.** Importing `rag_local` (lancedb + pyarrow)
  costs about 10s and 89MB on this machine, so it is imported *inside* the search-backed tools
  only; `list_notes` / `get_note` / `vault_status` touch the filesystem and never pay it.
- **`.mcp.json` is project-scoped on purpose** — sessions in unrelated repos do not load the vault
  tools and do not spend tokens on them.
- **One watcher, one inbox.** Duplicate instances are blocked by a socket bind on port 47823
  (the OS reclaims it on a crash, unlike a lock file). The scheduled task triggers **at logon, not
  at boot** — iCloud Drive is per-user, and a session-0 task only ever sees placeholders it cannot
  hydrate.
- **Do not change `EMBED_DIM` without a `--reset` re-index.** The dimension is baked into the Lance
  schema; the loud mismatch check in `embed()` is the safety net, not an obstacle.

## Open items

1. Telegram messages render `**bold**` literally (`send_message` sets no `parse_mode`). Cosmetic.
2. `rag_db.baseline-20260731/` is still on disk — keep until the current index is proven stable,
   then delete.
3. Untracked strays in the repo root (`2002.08909v1_*.pdf`, `udikw_202606_003.pdf`, `-003-1`,
   `-006`, `-010`) — acknowledged, not yet sorted.
4. The separate company RAG on STRX-D75 has not started.
5. Remaining ROADMAP items (reranker tuning, Docling for native-PDF tables) are untouched.
