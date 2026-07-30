# Archive Pipeline — Roadmap & Future Hand-off

> **Purpose of this document:** give a future contributor (human or AI) the *context* —
> the concept, the why behind decisions, and where to go next — not just the code.
> For the as-built technical detail, see [`SYSTEM-HANDOFF.md`](SYSTEM-HANDOFF.md).
> The original RAG vision is in [`archive-pipeline-handoff.md`](archive-pipeline-handoff.md).
>
> Owner: a non-programmer Korean architect / BIM manager. **Read "Working with the owner" below before making changes.**
> Last updated: 2026-07-29.

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
| **Classifier: pin `gemini-3.1-flash-lite` (GA), REJECT `gemini-3.5-flash-lite` (2026-07-29)** | 10-run A/B at temperature 0 on real documents: 3.1 gave 10/10 identical titles; 3.5 gave 9/10 and twice emitted categories outside the controlled `DOC_TYPES` vocabulary (기록지, 기타), plus mis-picked 체크리스트 for a training log. `category` becomes the note filename, so drift there fragments the vault. Cheaper too ($0.25 in/$1.50 out vs $0.30/$2.50 per 1M tokens). **Lesson: newer and pricier lost to older on a heavily tuned instruction-following prompt.** | `classifier/classify.py`, `.env LLM_PROVIDER=gemini` |
| **Cap thinking on the RAG answer path (2026-07-30)** | Unconstrained, `gemini-3.5-flash-lite` took 37–119s per answer; capped, 2.1–2.6s with the same answers. A conversational bot cannot wait two minutes. The retrieved context is already in the prompt, so extended reasoning buys nothing here. | `rag_local._generate` |
| **Answer model: `gemini-3.1-flash-lite`; `gemini-3.5-flash` rejected (2026-07-30)** | 3.5-flash returned 503 on 4/4 attempts even with retries (capacity, not our bug). The two Lite models showed **no measurable quality difference** on real vault questions, so the cheaper/faster one wins, and it is already the classifier model. Swappable via `.env` with no re-index — both embedders are 3072-dim. | `.env RAG_GEN_MODEL` |
| **Verify embedding count and dimension before indexing (2026-07-30)** | `gemini-embedding-2` returns ONE vector for a multi-input request **without erroring**. Used as-is, chunks and vectors misalign and retrieval silently degrades — the worst failure class here, since nothing looks broken. | `rag_local.embed` |
| **Qwen evaluated as a Gemini replacement across all four cloud seams — viable, not yet executed (2026-07-31)** | Research only, no code. All four seams (classifier/OCR/embeddings/answers) can move to Alibaba Model Studio via its OpenAI-compatible endpoint, at 2-5x lower cost, with Qwen3 open weights giving a same-family local fallback that Gemini cannot. Risk is uneven: embeddings and answers are low-risk, the classifier must re-run the same 10-run temp-0 vocabulary A/B, and OCR must re-pass the 685-317 fixture character-exact. Recommendation is to add `qwen` as a *third* provider, not to replace Gemini, so the A/Bs are possible at all. Full model list, prices, and the four behavioral traps: `learnings/2026-07-31-qwen-vs-gemini-evaluation.md` | (no code yet) |
| **Cloud OCR (`OCR_PROVIDER=gemini`) added as a second scan-OCR route, alongside Tesseract (2026-07-29)** | Needed for machines with no Tesseract (see "Multi-machine operation" below). Renders pages with PyMuPDF and sends them to a vision model for verbatim transcription — **no binarization** (that preprocessing helps Tesseract but hurts vision models). Verified on the same 685-317 대수선 필증 scan that EasyOCR previously misread (`685-317`→`685-377`): Gemini transcribed every critical value exactly (lot number, area, amount, date, company name). This does **not** reverse the Track 2 rejection below — EasyOCR/PaddleOCR are still rejected for *local* digit misreads; this is a different, cloud vision route. | `extractors/extract.py` |

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
- **Extraction quality upgrade (Docling / PaddleOCR).** ⚠️ EVALUATED 2026-07-06 — **do not swap
  scan OCR now.** A/B on the 685-317 대수선 필증 scan (isolated venvs, production deps untouched):
  - *Tesseract (current):* doubles chars in the header (`발발급급확확인인번번호호`) BUT reads the
    critical lot numbers correctly (685-317, 성수동1가, 2018.11.29).
  - *EasyOCR (ko):* fixes the header doubling and runs on Py3.13/GPU, BUT **misreads lot-number
    digits** (685-317→685-**377**, 성수동1가→성수동**7**가) — dangerous, since project detection and
    the whole construction domain hinge on those exact numbers. Net: not a safe upgrade.
    Also multi-GB torch on a VRAM-constrained shared machine.
  - *PaddleOCR (CJK-strong, the best candidate on paper):* installs on Py3.13 but the CPU
    paddlepaddle 3.x build hits an oneDNN/PIR inference bug here (`ConvertPirAttribute2Runtime
    Attribute`) — not runnable without a different paddle build.
  - *Docling (full pipeline):* transformers 4.x/5.x lazy-import filesystem scan crashes in this
    env; its real value is **native-PDF table structure**, not scan OCR, so it's the wrong tool
    for the garbled *scans* anyway.
  - **Conclusion / next:** the Track 3 metadata-stamping already neutralizes most OCR-noise impact
    on RAG (clean frontmatter carries date/project/category), so an OCR swap is low-payoff + risky
    right now — keep Tesseract. The genuinely valuable, untested axis is **Docling for NATIVE
    (non-scanned) PDFs with real tables** (견적서/내역서 → markdown tables); revisit that in a
    clean env (pin `transformers`, install outside a temp dir), on-demand only, and never route
    Korean *scans* through a digit-misreading engine. Re-processing filed notes needs `_archive`.
  - **Cloud OCR alternative (2026-07-29) — this does NOT reverse the rejection above.** Added
    `OCR_PROVIDER=gemini` as a second route alongside Tesseract, for machines with no Tesseract
    install (see "Multi-machine operation" below). It's a cloud vision model, not a local engine,
    so the EasyOCR/PaddleOCR digit-misread problem doesn't apply the same way — verified on the
    same 685-317 scan with every critical value transcribed exactly. Tesseract stays the default
    everywhere it's available; this is an option for hardware that can't run it at all.

### Phase 8 — Smarter retrieval (local RAG follow-ups from the 2026-07-06 migration)
> RAG is now in-process (`rag_local.py`: LanceDB + bge-m3). These items build on it.
- **Answer grounding (DONE 2026-07-08).** Fixed the "bot won't read facts from garbled scans"
  problem without a reranker: each note stores its clean `## 요약` (summary column); at answer
  time chunks are grouped by note with the summary prepended. Also fixed 3 answer-breaking bugs
  (num_ctx=8192 → 1-char replies; oversized OCR chunks overflowing context; one note monopolizing
  the top-k). Tuning knobs in `rag_local.py`: `DEFAULT_K`, `CONTEXT_CHAR_BUDGET`,
  `MAX_CHUNKS_PER_NOTE`, `GEN_NUM_CTX`.
- **Hybrid search** (BM25/full-text + semantic). ◻ OPTIONAL remaining. Still helps ambiguous
  queries where the embedding blurs proper nouns / lot numbers (685-317 vs 685-383). LanceDB has
  a native full-text index (`create_fts_index`) + `RRFReranker` to combine keyword + vector scores
  (no model download). Caveat to test: tantivy's Korean tokenization is weak for space-less
  Hangul; may need an ngram tokenizer. Lower priority now that summary-grounding handles most
  factual misses.
- **Re-rank.** ◻ OPTIONAL. A cross-encoder reranker (e.g. bge-reranker-v2-m3) over the top-k
  would pull the exact right note above same-지번 siblings — but adds a model + the torch/
  transformers dependency weight we hit trouble with in Track 2. Only if hybrid isn't enough.
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

### Where this repo runs, and what it is for (decided 2026-07-29)
**This repo is the owner's personal-use pipeline, and n100-win (`NUCBOXG2`, an Intel N100 mini PC
with no Ollama and no Tesseract) is its permanent home.** It runs on cloud backends selected purely
via that machine's own gitignored `.env` (`LLM_PROVIDER=gemini`, `OCR_PROVIDER=gemini`), so no other
machine's configuration is touched. STRX-D75 is not expected to run this pipeline any more.

**Company/client material gets a separate RAG on STRX-D75, built later and out of scope here.** The
split is deliberate: personal material may go to a cloud API, company material should stay local on
the GPU box. Two consequences the owner has explicitly accepted:
- Input remains the shared iCloud `_inbox` and notes remain in `KC_second_brain`. Company documents
  dropped in for scheduling/study purposes **will** be sent to the cloud API by this pipeline.
- Turning the Telegram bot on here means embedding the whole vault, including the existing
  `10_Professional` notes, through the cloud API once.

If a second machine is ever pointed at the same inbox, note that `processed_hashes.json`,
`_archive`, and `processing_log.csv` are per-machine, so two simultaneous watchers can process the
same file twice into duplicate notes. Run one watcher at a time.

### Phase 9 — Safety & ops
- **Sensitivity pre-flag.** Regex/heuristics to flag notes containing personal data (주민번호,
  account numbers, contract amounts) — tag or quarantine for review before they're broadly searchable.
- **Vault backup strategy.** Migrations already zip the vault; formalize a scheduled backup
  (the `vault_backup_*.zip` files are gitignored and pile up — prune or rotate).
- **Vault dedup cleanup.** ✅ DONE 2026-07-31 via `migrate_dedupe_notes.py` (backup → dry-run →
  `--execute`). The estimate of "~4 duplicates" was well short: 23 title-collision groups covering
  51 notes. **20 folded, 15 renamed, 231 notes remain.** Three things the work turned up:
  - A title group can hold *both* duplicates and distinct documents, so clustering has to happen
    **within** each group. One 견적서 group was 1 bundle of 119,298 chars plus 3 near-identical
    내역서; folding the group wholesale would have destroyed real material.
  - A fixed similarity threshold misjudges short notes, where a few characters swing the ratio.
    Notes sharing the **same `source` file** fold at a lower bar (0.90), since the same file cannot
    produce two revisions.
  - Notes are referenced by `[[wikilinks]]`. Keeping the *linked* member of each cluster meant
    zero links needed rewriting; deleting naively would have broken 2 silently.
- **Index must mirror the vault.** ✅ DONE 2026-07-31. `ingest` previously only added and updated,
  never removed, so notes deleted or renamed by hand lingered in the index forever and the bot
  cited notes that no longer existed (4 such ghosts had accumulated). It now prunes rows whose note
  is gone from the vault.
- **Disk hygiene.** ✅ DONE 2026-07-08 — removed ~61GB of unused Ollama models with owner's OK
  (gemma4:26b/e4b, codestral, qwen2.5:14b, qwen3.5, mistral-nemo, nomic-embed-text). Kept the
  three the pipeline uses: `exaone3.5:7.8b`, `bge-m3`, `llama3.1`.

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
