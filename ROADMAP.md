# Archive Pipeline — Roadmap & Future Hand-off

> **Purpose of this document:** give a future contributor (human or AI) the *context* —
> the concept, the why behind decisions, and where to go next — not just the code.
> For the as-built technical detail, see [`SYSTEM-HANDOFF.md`](SYSTEM-HANDOFF.md).
> The original RAG vision is in [`archive-pipeline-handoff.md`](archive-pipeline-handoff.md).
>
> Owner: a non-programmer Korean architect / BIM manager. **Read "Working with the owner" below before making changes.**
> Last updated: 2026-07-06.

---

## 1. Roadmap at a glance

```
        ┌─────────────────────────────────────────────────────────────────────┐
PHASE 0 │ Ingestion pipeline      drop file → extract → classify → note → archive   ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 1 │ Robustness & autonomy   OCR, HWP/HWPX, dedup, quarantine, Telegram alerts,
        │                         Task Scheduler autorun, iCloud hydration guard      ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 2 │ Knowledge / vault       tag-based schema v2, time folders, migrations       ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 3 │ RAG layer               local RAG: LanceDB + bge-m3 (was Open WebUI+MiniLM)   ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 4 │ Conversational access   Telegram bot (RAG, EXAONE 3.5), resource monitor,
        │                         pause/resume for Revit/Enscape                       ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 5 │ Project awareness       project: field on work notes (single project today)  ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 6 │ Multi-project           project DETECTION done (identifier-based); config a
        │                         2nd project + project-scoped RAG remain              ◧ PARTIAL
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 7 │ Richer inputs           voice (Whisper), sketch/vision (VLM), more formats   ◻ FUTURE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 8 │ Smarter retrieval       hybrid search, auto re-ingest, project-scoped RAG    ◻ FUTURE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 9 │ Safety & ops            sensitivity pre-flag, vault backup, dedup cleanup    ◻ FUTURE
        └─────────────────────────────────────────────────────────────────────┘
```

**The single most likely next trigger:** a second project arrives → do Phase 6 (project detection). Everything else is opportunistic.

---

## 2. Concept & purpose

**What it is:** a personal, fully-local "second brain" pipeline. The owner drops any work or
personal document into a watched folder; the system reads it (even scanned/Hangul files),
understands and files it as a clean Obsidian note with tags, archives the original, and makes
everything queryable in natural Korean — from a phone, via Telegram.

**Why it exists:** the owner handles many construction/architecture documents (contracts,
estimates, meeting notes, tax invoices, drawings-adjacent paperwork) in Korean, much of it
scanned or in Hangul (HWP). Manually organizing and recalling this is slow. The goal is
*zero-effort capture + instant recall* without changing how they already work.

**Guiding principles (these shaped almost every decision):**
1. **Local-first / private.** No cloud LLMs. Documents never leave the PC. Only Telegram
   question/answer text transits the network (and even that is opt-in).
2. **Minimal machine footprint.** The owner is a non-programmer and shares machine conventions
   with others; "compatibility is priority." Prefer fixing things *in code* over changing
   system/global settings.
3. **Hands-off.** After the PC boots, it should just work — no manual steps.
4. **Korean-native quality.** Korean OCR, Korean embeddings, Korean-native LLM.
5. **Coexist with heavy GPU work.** The same PC runs Revit/Enscape; the AI stack must yield
   RAM/VRAM on demand.

---

## 3. Decision log — the "why" behind the build

| Decision | Why | Where |
|---|---|---|
| Pin Ollama client host to `127.0.0.1` in code, leave machine `OLLAMA_HOST=0.0.0.0` | Machine env var is unconnectable on Windows, but owner wants no machine changes → fix in code | `classifier/classify.py` |
| Tags, not deep folders (schema v2: `10_/20_/90_` + `YYYY-QN`) | Obsidian-native, RAG-friendly, avoids brittle deep hierarchies; time folders keep things shallow | `notes/write_note.py` |
| YAML frontmatter, rejected the original `<METADATA>` block idea | Frontmatter is Obsidian-native and embeds cleanly into RAG | (rejected handoff proposal) |
| Korean OCR = grayscale + autocontrast + **binarize@150** + `--psm 6` | Korean scans are near-unreadable without binarization | `extractors/extract.py` |
| Classifier: trim to 4000 chars, restate schema *after* content, retry at rising temps | Long scans made the LLM ignore the schema (missing `domain`); recency + retries fixed it | `classifier/classify.py` |
| Archive folder **outside** iCloud | Save iCloud storage; originals don't need syncing | `.env ARCHIVE_DIR` |
| iCloud **hydration guard** (download with timeout before reading) | Online-only placeholder files blocked the pipeline indefinitely | `pipeline.py` |
| Resource **black-box monitor** (RAM/CPU/GPU/models every 30s) | A hard freeze left no diagnostic data; prime suspect was `gemma4:26b` (18GB) overflowing the 16GB GPU | `monitor.py` |
| **pause/resume** scripts, **no keep-warm** | Revit/Enscape need the VRAM; owner accepts ~5-10s first-answer delay | `pause_ai.ps1`, `resume_ai.ps1` |
| Open WebUI bound to **127.0.0.1 only** | It was exposed on the tailnet where another user (`jisoo.park@`) lives; the vault is private | container run args |
| **Local RAG** (LanceDB + bge-m3) replaced Open WebUI (2026-07-06) | Open WebUI's default embedder was silently **all-MiniLM-L6-v2 (English)** → poor Korean recall; and Docker was an oversized, failure-prone middle layer (went down unnoticed; upgrades wiped the KB). In-process LanceDB removes that class of failure. `RAG_BACKEND` toggles back to `openwebui` as fallback | `rag_local.py`, `telegram_bot.py` |
| Embedder = **bge-m3** (not nomic/MiniLM) | Multilingual; far better Korean recall. Now run locally via Ollama (1024-dim) | `rag_local.py` |
| Chunks stamped with note **frontmatter** (title/date/category) | Scan OCR is noisy; the clean metadata lets date/category questions answer precisely | `rag_local.py _split_note` |
| Telegram bot via **outbound long-poll** | Phone access from anywhere with **no inbound ports / no tunnel**; vault stays home | `telegram_bot.py` |
| Bot answers **only the owner's chat_id** | It's a private brain | `telegram_bot.py` |
| Bot model = **EXAONE 3.5 7.8B** (benchmarked vs mistral-nemo, qwen2.5-14B) | Korean-native won on fluency, grounding, speed, *and* smallest VRAM. The 14B model was worst (slow, drifted to Chinese). **Lesson: bigger ≠ better for Korean RAG.** | `bench_models.py`, `.env` |
| Avoid "thinking" models for the bot (qwen3.5, gemma4:e4b, exaone-deep) | Thinking output goes to `reasoning_content`, leaving `content` empty | benchmark finding |
| RAG prompt **enforces grounding** (don't fall back to general knowledge) | A permissive prompt made the smart model ignore the notes and answer generically | Open WebUI `RAG_TEMPLATE` |
| `TOP_K=10` | Owner felt answers referenced too few notes | Open WebUI config |
| `project:` field = **deterministic default**, not LLM-guessed | All work is one project today; LLMs name it inconsistently. Deterministic now, add detection later | `notes/write_note.py` |

---

## 4. Current state (one paragraph)

Everything in Phases 0–5 runs under one Windows Task Scheduler job (`ArchivePipelineWatch`)
that starts on boot and launches three daemon threads: the file **watcher**, the **resource
monitor**, and the **Telegram bot**. RAG runs **in-process** (`rag_local.py`: LanceDB + bge-m3,
no Docker) over ~236 vault notes; Open WebUI remains only as an env-selectable fallback
(`RAG_BACKEND=openwebui`), pending decommission. The owner drops files into the iCloud
`_inbox`; notes land in the Obsidian vault with tags and (for work) a `project` field; the
original is archived locally; and the owner can ask questions in Korean from their phone.
`pause_ai.ps1` frees ~9GB RAM + all VRAM before Revit/Enscape. See `SYSTEM-HANDOFF.md` for files.

---

## 5. Future work backlog (addendum ideas)

Ordered roughly by value-to-effort. Each is independent.

### Phase 6 — Multi-project (the likely next need)
- **Project detection.** ✅ DONE (2026-07-06). `classify.detect_project()` assigns `project` per
  note from deterministic identifiers (lot numbers/addresses); `Classification.project` field;
  `write_note` uses it, falling back to `DEFAULT_WORK_PROJECT`. Registry = `DEFAULT_WORK_PROJECT`
  + `PROJECT_IDENTIFIERS` plus optional `WORK_PROJECTS` JSON in `.env`. **When a 2nd project
  arrives:** add it to `WORK_PROJECTS`, then run `migrate_add_project.py` (dry-run → `--execute`)
  to re-file existing notes by their `source` filename. (LLM inference was deliberately NOT used —
  lot numbers are cleaner and the decision log warns LLMs name projects inconsistently.)
- **Project-scoped RAG.** ◻ Remaining. Filter `rag_local` search by the `project` column (a
  `/project 성수동` command, or detect project from the question) so the bot answers within one
  project. LanceDB supports a `where` filter on the query.
- **Project-scoped RAG.** Let the Telegram bot filter retrieval by project (e.g. a `/project 성수동`
  command, or detect project from the question). Open WebUI supports metadata filtering.

### Phase 7 — Richer inputs
- **Voice capture (Whisper).** Local `whisper`/`faster-whisper` to transcribe voice memos
  dropped as audio files → same classify/note path. Owner can dictate site notes.
- **Sketch / drawing understanding (VLM).** A vision model (Qwen2-VL / LLaVA-class) to describe
  hand sketches or marked-up drawings into searchable text. Watch VRAM (coexist with Enscape).
- **More formats.** ✅ `.xlsx` (estimates/내역서), `.docx`, `.msg` (emails), `.xml` (전자세금계산서)
  are now extracted and routed through the pipeline. Still future: `.pptx`, archive expansion
  (`.zip`/`.alz`), `.dwg` metadata.
- **Extraction quality upgrade (Docling / PaddleOCR).** Tesseract on Korean scans produces
  garbled text — observed character-doubling on the 685-317 대수선 필증 scan
  (`발발급급확확인인번번호호`), and loses table/layout structure. Plan: **Docling** for native/
  complex PDF + office docs (structure→markdown, tables preserved), **PaddleOCR** (CJK-strong)
  for Korean scans; keep tuned Tesseract as fallback and A/B before adopting. Heavy deps (torch)
  → run **on-demand only**, add to `pause_ai`, mind the 16 GB VRAM shared with Revit/Enscape.
  Re-processing already-filed notes needs the archived originals in `_archive`.

### Phase 8 — Smarter retrieval (local RAG follow-ups from the 2026-07-06 migration)
> RAG is now in-process (`rag_local.py`: LanceDB + bge-m3). These items build on it.
- **Hybrid search** (BM25/full-text + semantic). The clearest gap: ambiguous queries where the
  embedding blurs proper nouns / lot numbers — e.g. "685-317 **건축**허가 필증" retrieves the
  685-383 **증축** note or 공정표 because "건축허가" is generic and 685-317 appears in many docs.
  LanceDB has a native full-text index (`create_fts_index`) → combine keyword + vector scores.
  This is the highest-value next step for retrieval accuracy.
- **Re-rank.** Add a cross-encoder reranker (e.g. bge-reranker-v2-m3 via Ollama/local) over the
  top-k before generation, to pull the exact right note above same-지번 siblings.
- **Auto re-ingest.** Today the index is refreshed by re-running `ingest_vault.py` (manual /
  `/my-vault` sync). Wire the watcher to index a note right after `pipeline.process_file` writes it
  (a targeted single-note `rag_local` call). Requirements so it stays sane: **best-effort /
  non-fatal** (an embed failure must not break filing), **graceful skip while `pause_ai` has Ollama
  stopped**, keep a **periodic full re-ingest as backstop** (covers the pause window + manual vault
  edits/renames the watcher never sees). Single-writer holds (watcher is serial; bot only reads),
  so LanceDB concurrency is fine. See "Auto-index feasibility" note below.
- **Project-scoped retrieval** once Phase 6 lands: filter LanceDB search by the `project` column.

**Auto-index feasibility (answering "is anything unreasonable about it?"):** No blocker — it's
cheap (bge-m3 ~1.2 GB, one small embed per new note) and safe (serial writer + read-only bot).
The only *irrational* ways to do it are (a) making it fatal to filing, or (b) full-scanning all
notes on every file. Avoid both: catch/skip on failure, index just the one note, and rely on the
periodic full re-ingest to catch anything missed during a `pause_ai` window or manual edit.

### Decommission — remove Open WebUI / Docker (after local RAG is proven in daily use)
Open WebUI is kept only as a fallback (`RAG_BACKEND=openwebui`). Once the local path is trusted:
drop the Docker dependency, simplify `run_watch.py` / `pause_ai.ps1` (no container to stop),
update the `/my-vault` skill (Op1 health check no longer needs `docker ps`), and remove the
`OPENWEBUI_*` config. Reclaims RAM and deletes an entire failure class.

### Phase 9 — Safety & ops
- **Sensitivity pre-flag.** Regex/heuristics to flag notes containing personal data (주민번호,
  account numbers, contract amounts) — tag or quarantine for review before they're broadly searchable.
- **Vault backup strategy.** Migrations already zip the vault; formalize a scheduled backup
  (the `vault_backup_*.zip` files are gitignored and pile up — prune or rotate).
- **Vault dedup cleanup.** ~4 genuine duplicate-content notes exist; a small script could fold them.
- **Disk hygiene.** Underperforming models (`qwen2.5:14b`, `qwen3.5`, `gemma4:26b`) take ~26GB
  and aren't used by the bot — removable with owner's OK.

### Quality-of-life
- **Double-click `.bat` shortcuts** for pause/resume (owner is a non-programmer).
- **Bot conveniences:** conversation memory (follow-ups), `/help` examples, maybe daily digest.
- **Deep-free option** (`wsl --shutdown`) to reclaim the last ~3GB before huge renders.

---

## 6. Working with the owner (important)

- **Non-programmer.** Explain *why* in plain language before changing anything; prefer
  reversible, code-level changes over machine/global settings.
- **Compatibility first.** Don't alter shared machine conventions or default app behavior.
- **Confirm before destructive/outward actions.** Deletes (files, KB resets, model removal) and
  anything that exposes data externally need explicit OK. The auto-permission classifier will
  also block these — that's expected, surface it to the owner.
- **The owner runs interactive commands themselves** via the `!` prefix (e.g. browser logins,
  scheduled-task registration the classifier blocks).

---

## 7. Onboarding checklist for a future contributor

1. Read `README.md`, then `SYSTEM-HANDOFF.md` (as-built), then this file (the why + what's next).
2. Config & secrets live in `.env` (gitignored); template in `.env.example`.
3. Run `python run_once.py` to process the inbox once; `pytest -q` for the test suite (52 tests).
4. The live system = the `ArchivePipelineWatch` task (watcher + monitor + bot). Restart with
   **Stop + Start** (no `Restart-ScheduledTask` on this PowerShell).
5. RAG runs locally in `rag_local.py` (LanceDB index at `rag_db/`, gitignored; embedder bge-m3,
   `DEFAULT_K`, `GEN_NUM_CTX` are constants there). Legacy Open WebUI knobs apply only when
   `RAG_BACKEND=openwebui`.
6. Persistent project memory for the AI assistant is in
   `~/.claude/projects/.../memory/` (indexed by `MEMORY.md`) — read it; it captures the gotchas.
```
