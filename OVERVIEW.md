# Archive Pipeline — Overview

A personal, **fully on-device** "second brain" for an architect/BIM manager who deals with a lot
of Korean construction paperwork. Drop a document in a folder → it gets read (even scanned/Hangul),
classified, and filed as a tagged Obsidian note → then you can ask questions about everything in
Korean, from your phone. No cloud, no data leaving the machine.

> For the curious: deeper docs are `ROADMAP.md` (the why + what's next) and `SYSTEM-HANDOFF.md`
> (as-built technical detail). This file is the 5-minute tour.

---

## The problem

Contracts, estimates (내역서), meeting notes, tax invoices — much of it **scanned** or in **HWP
(Hangul)**, all in Korean. Capturing and *recalling* it manually is slow. Goal: zero-effort
capture + instant recall, without changing how the owner already works.

## What it does

```
   Drop file in _inbox (iCloud)
            │
            ▼
   ┌──────────────────────────────────────────────┐
   │  watcher (watchdog)                            │
   │   1. dedupe (SHA-256)                          │
   │   2. extract text                              │
   │        • PDF: pdfplumber → OCR fallback        │
   │          (PyMuPDF render + Tesseract kor+eng,  │
   │           binarized — Korean scans need it)    │
   │        • HWP/HWPX (Hangul), images, txt/md     │
   │   3. classify + summarize (local LLM → JSON)   │
   │   4. write Obsidian note (YAML tags + project) │
   │   5. archive original (outside iCloud)         │
   └──────────────────────────────────────────────┘
            │                              │
            ▼                              ▼
   Obsidian vault                  Local RAG (in-process)
   10_/20_/90_ + YYYY-QN           LanceDB + bge-m3, no Docker
   tag-based, shallow                       │
                                            ▼
                                 Telegram bot ──► ask from your phone (Korean)
```

Everything runs as one Windows Task Scheduler job (watcher + resource monitor + Telegram bot,
each a daemon thread) that starts on boot. ~236 notes currently indexed. New notes are auto-indexed
into the RAG right after filing (hourly full re-index as backstop).

## Stack (all local)

| Layer | Tool |
|---|---|
| LLM runtime | **Ollama** |
| Classify/summarize | llama3.1 (JSON-mode, schema-hardened for long scans) |
| Embeddings | **bge-m3** (multilingual, strong Korean), via Ollama |
| Chat / RAG answers | **EXAONE 3.5 7.8B** (LG's Korean-native model) |
| RAG orchestration | **local, in-process** — LanceDB (file-based vector index) + hybrid full-text search; no Docker. (Legacy Open WebUI selectable via `RAG_BACKEND=openwebui`) |
| OCR | Tesseract (kor+eng) + PyMuPDF for scanned PDFs |
| Hangul | pyhwp (.hwp), zip+OWPML parse (.hwpx) |
| Watch / autorun | watchdog + Windows Task Scheduler |
| Chat interface | Telegram Bot API (stdlib urllib) |
| Notes | Obsidian (iCloud-synced), YAML frontmatter |

Hardware: i9-14900KF / 64GB RAM / RTX 4080 (16GB). Python 3.13 on Windows 11.

## A few decisions worth stealing

- **Telegram bot uses outbound long-polling**, so you can query from anywhere with **zero inbound
  ports / no tunnel** — the PC dials out to Telegram; the vault never leaves home. Bot answers only
  the owner's chat ID.
- **Korean-native model beat the bigger generalists.** Benchmarked EXAONE 3.5 7.8B vs mistral-nemo
  12B vs Qwen2.5 14B on real documents: EXAONE won on fluency, grounding, *and* speed — and used
  the least VRAM. The 14B model was worst (slowest, drifted into Chinese). **Bigger ≠ better for
  Korean RAG.**
- **"Thinking" models were unusable here** — their output went to `reasoning_content` and left the
  answer empty through the API. Plain instruct models won.
- **RAG prompt must enforce grounding.** A permissive "use general knowledge if needed" prompt made
  the model ignore the notes and answer generically. Locking it to the retrieved context fixed it.
- **Scanned Korean OCR needs binarization** (threshold + `--psm 6`) — grayscale alone is near-useless.
- **iCloud online-only placeholders** block file reads indefinitely; a hydration guard downloads
  with a timeout before the pipeline touches a file.
- **Coexists with Revit/Enscape** via a pause/resume script that frees ~9GB RAM + all VRAM on demand
  (no model keep-warm — a ~5-10s first-answer delay is the accepted trade).

## Status

Working end to end: capture → classify → tagged/project-tagged notes → local RAG → Telegram.
RAG moved off Open WebUI to an in-process LanceDB + bge-m3 stack (better Korean recall, no Docker
failure class); project *detection* from lot numbers is in; answers are grounded with each note's
clean summary and hybrid search. Optional next steps (reranker, project-scoped RAG) in `ROADMAP.md`.
```
