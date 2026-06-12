# Archive Pipeline — Roadmap & Future Hand-off

> **Purpose of this document:** give a future contributor (human or AI) the *context* —
> the concept, the why behind decisions, and where to go next — not just the code.
> For the as-built technical detail, see [`SYSTEM-HANDOFF.md`](SYSTEM-HANDOFF.md).
> The original RAG vision is in [`archive-pipeline-handoff.md`](archive-pipeline-handoff.md).
>
> Owner: a non-programmer Korean architect / BIM manager. **Read "Working with the owner" below before making changes.**
> Last updated: 2026-06-10.

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
PHASE 3 │ RAG layer               Open WebUI + bge-m3, vault ingested, localhost-only  ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 4 │ Conversational access   Telegram bot (RAG, EXAONE 3.5), resource monitor,
        │                         pause/resume for Revit/Enscape                       ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 5 │ Project awareness       project: field on work notes (single project today)  ✅ DONE
        ├─────────────────────────────────────────────────────────────────────┤
PHASE 6 │ Multi-project           project DETECTION when a 2nd project appears         ◻ NEXT
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
| Embedder = **bge-m3** (not nomic/MiniLM) | Multilingual; far better Korean recall. Switching dims requires KB reset + re-ingest | Open WebUI config |
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
monitor**, and the **Telegram bot**. Open WebUI runs in Docker (localhost-only) as the RAG
engine over a bge-m3 knowledge base of ~185 vault notes. The owner drops files into the iCloud
`_inbox`; notes land in the Obsidian vault with tags and (for work) a `project` field; the
original is archived locally; and the owner can ask questions in Korean from their phone.
`pause_ai.ps1` frees ~9GB RAM + all VRAM before Revit/Enscape. See `SYSTEM-HANDOFF.md` for files.

---

## 5. Future work backlog (addendum ideas)

Ordered roughly by value-to-effort. Each is independent.

### Phase 6 — Multi-project (the likely next need)
- **Project detection.** When a 2nd project appears, infer `project` per note instead of the
  fixed default. Approach: keyword/address match first (e.g. "성수동", lot numbers like
  685-317), LLM inference as fallback. Add `project` to the `Classification` schema, keep a
  configurable list of known projects. Backfill is already solved by `migrate_add_project.py`'s pattern.
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

### Phase 8 — Smarter retrieval
- **Hybrid search** (BM25 + semantic). Helps Korean proper nouns / lot numbers that embeddings
  blur (685-317 vs 685-383). Toggle `ENABLE_RAG_HYBRID_SEARCH` in Open WebUI and tune weights.
- **Auto re-ingest.** Today the KB is a manual snapshot. Make new/changed vault notes sync into
  the KB automatically (e.g. the watcher calls the ingest API after writing a note). Mind the
  reset/dedup quirks documented in `SYSTEM-HANDOFF.md` / memory.
- **Re-rank** for tighter top results (Open WebUI supports a reranker model).

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
3. Run `python run_once.py` to process the inbox once; `pytest -q` for the test suite (24 tests).
4. The live system = the `ArchivePipelineWatch` task (watcher + monitor + bot). Restart with
   **Stop + Start** (no `Restart-ScheduledTask` on this PowerShell).
5. RAG knobs live server-side in the `open-webui` Docker volume (TOP_K, embedder, RAG_TEMPLATE) —
   NOT in git. Change via the `/api/v1/retrieval/*` endpoints.
6. Persistent project memory for the AI assistant is in
   `~/.claude/projects/.../memory/` (indexed by `MEMORY.md`) — read it; it captures the gotchas.
```
