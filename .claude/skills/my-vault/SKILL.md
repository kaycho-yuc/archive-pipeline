---
name: my-vault
description: Operate the archive-pipeline personal knowledge vault — check health, sync notes to the Telegram RAG bot, add a project, confirm notes whose project is 미정/unassigned, or diagnose a freeze. Invoke when the user wants to run, check, fix, or extend their document pipeline / second-brain / Obsidian-RAG / Telegram bot system.
---

# Personal Vault — operations hub

This is the owner's one-word entry point to operate their local document pipeline +
RAG + Telegram bot. The owner is a **non-programmer** and returns infrequently, so:

- **Always start by presenting the menu below** (and a quick health summary), then do what they pick.
- Explain in plain language. Confirm before anything destructive (deletes, KB resets, model removal).
- Project root: `C:\Users\OWNER\Documents\archive-pipeline`. Config/secrets in `.env`.
- Background context lives in `OVERVIEW.md`, `ROADMAP.md`, `SYSTEM-HANDOFF.md`, and the
  assistant memory at `~/.claude/projects/.../memory/` — consult them for the "why".

## What to do when invoked

1. Run the **health check** (operation 1) and show a short status table.
2. Present this menu and ask which they want:

   ```
   무엇을 할까요? (What would you like to do?)
   1) 상태 점검        — is everything working?
   2) 볼트 → 봇 동기화  — push new/edited notes into the Telegram bot's knowledge
   3) 프로젝트 추가     — set up a new project (beyond 성수동 리모델링)
   4) 멈춤 원인 진단    — diagnose a freeze / slowdown
   5) 미정 노트 확정    — assign a project to notes the pipeline could not identify
   ```

3. Execute the chosen operation below.

---

## Operation 1 — Health check (read-only, safe)

Report each as ✅/❌ with one line:

- **Watcher task:** `Get-ScheduledTask ArchivePipelineWatch` → State should be `Running`.
- **Ollama:** `Invoke-WebRequest http://127.0.0.1:11434/api/tags` → 200; `ollama ps` for loaded models.
- **Open WebUI:** `docker ps` → `open-webui` Up & `127.0.0.1:3000` (must be localhost-only, NOT 0.0.0.0).
- **Monitor:** tail `resource_log.csv` → rows within the last ~minute means it's logging.
- **Recent processing:** tail `processing_log.csv` and `watch.log` for the latest results / errors.
- **Bot model:** read `TELEGRAM_RAG_MODEL` from `.env` (currently `exaone3.5:7.8b`).

If the watcher is stopped, restart it with **Stop then Start** (this PowerShell has **no**
`Restart-ScheduledTask`):
`Stop-ScheduledTask ArchivePipelineWatch; Start-Sleep 2; Start-ScheduledTask ArchivePipelineWatch`.

If Open WebUI is missing after a reboot/crash, recreate it **localhost-only**:
`docker run -d --name open-webui --restart always -p 127.0.0.1:3000:8080 -v open-webui:/app/backend/data --add-host=host.docker.internal:host-gateway ghcr.io/open-webui/open-webui:main`

## Operation 2 — Sync vault → bot knowledge base

Use when the owner added/edited notes and wants the Telegram bot to know them.

Run `uv run python ingest_vault.py` (it reads `OPENWEBUI_*` from `.env`). Gotchas to apply:

- **Warm the embedder first** so it doesn't fail on cold start:
  `POST http://127.0.0.1:11434/api/embeddings {"model":"bge-m3","prompt":"warmup"}`.
- The script already **retries** the transient "Cannot connect to host" 400 (Ollama reload).
- For a **clean** rebuild (after many edits), reset first — but warn the owner this is destructive:
  `POST /api/v1/knowledge/{KB}/reset` then `DELETE /api/v1/files/all`, then re-run.
- **Do NOT trust the OK/fail tally** — KB `reset` doesn't clear the content-hash dedup, so you'll
  see many "Duplicate content detected" that are actually fine. **Verify with coverage queries**
  (`POST /api/v1/retrieval/query/collection`) across a few topics, and the authoritative linked
  count from a `file/add` response. KB id is in `.env` (`OPENWEBUI_KB_ID`).

## Operation 3 — Add a new project

This is **config, not code** — the detection machinery already exists. Do not offer to write code.

A work note's `project` comes from `classify.detect_project()`, which looks for registered
identifiers (lot numbers like `685-317`, addresses, the project name itself) in the original
filename and the `## 원문` body. Nothing matches → `project: 미정` and a Telegram notification.
The LLM never names a project; it only reports a `site` string that is fed back into the same
registry lookup.

1. Add the project to `.env`:
   `WORK_PROJECTS={"판교 오피스":["521-3","판교"]}` (JSON, project name → identifiers).
   Pick identifiers that cannot appear in another project's documents. A bare district name like
   `성수동` is too loose — it also matches 성수동2가 314-38, a different site.
2. Preview the effect on existing notes: `uv run python migrate_add_project.py --redetect`.
   Read every `old → new` line before continuing. Expect only intended moves.
3. Apply: `uv run python migrate_add_project.py --redetect --execute` (writes a backup zip first).
4. Confirm anything left at 미정: `uv run python review_pending.py --fix`.
5. Re-sync the bot (Operation 2).

Checkable result: re-running step 2 reports `변경 대상 0개`, and `review_pending.py` lists only
notes the owner deliberately left unconfirmed.

## Operation 5 — Confirm notes whose project is 미정

`uv run python review_pending.py` lists them (path, source filename, and the `site` string the
classifier read). `--fix` walks through them one at a time, applies all choices after one final
confirmation, backs up first, and re-indexes each changed note.

If the correct project is not on the menu, it is not registered yet — do Operation 3 first, then
come back. Skipping is safe; the note stays 미정 and reappears next run.

Do **not** "fix" these by editing `.env DEFAULT_WORK_PROJECT` or by re-adding a fallback. Filling
an unknown project with a default is the bug this replaced: on 2026-08-02 that fallback was found
to have force-filled 60 of 192 work notes, including documents from other sites.

## Operation 4 — Diagnose a freeze / slowdown

The resource monitor is the black box. Read the **last rows** of `resource_log.csv`
(columns: time, ram_used_gb, ram_total_gb, cpu_pct, gpu_mem_used_mb, gpu_mem_total_mb,
gpu_util_pct, ollama_models). Look for:

- **VRAM near 16 GB** with a big model loaded → the known freeze cause is `gemma4:26b` (18 GB)
  overflowing the 16 GB RTX 4080. Never let the bot/Open WebUI auto-load it; keep the bot on a
  small model (`exaone3.5:7.8b`).
- The **last row before a gap** = the state right before the freeze.
- High RAM with Revit/Enscape running → suggest `pause_ai.ps1` to free ~9 GB RAM + all VRAM
  before heavy GPU work; `resume_ai.ps1` to bring the AI stack back.

---

## Note schema & naming convention

- Work-note titles: **`YYYY-MM-DD <type> - <counterparty> (<detail, status>)`** (ISO 8601 + RDM/
  Dublin Core). Frontmatter: `title, domain, project, category, doc_date, counterparty, status,
  tags, source, created`. The classifier is **filename-first** (`source` filename is authoritative).
- **Reference material** (templates/samples/govt manuals/other-site) → quarantined to
  `_failed/참고자료`, never embedded. The bot answers from project data only.
- To re-title/clean existing work notes: `uv run python migrate_revise_notes.py` (dry-run shows
  every old→new + caches a plan) → review with owner → `uv run python migrate_revise_notes.py
  --execute` applies the cached plan. **Auto-classification isn't perfect on noisy OCR — always
  surface the dry-run for owner review; nothing is deleted and `source` is preserved.** Re-ingest
  after (Operation 2).

## Notes for the assistant

- Prefer the project's own tools/scripts over ad-hoc commands.
- Run `uv run python run_once.py` to process the inbox once on demand; `uv run pytest -q` for the suite.
- Env is uv-managed (`.venv`, `uv.lock`). The autorun task runs `.venv\Scripts\pythonw.exe run_watch.py`.
- Never expose Open WebUI beyond `127.0.0.1` (another tailnet user must not reach the private vault).
- This skill is a runbook for interactive use; unattended automation stays in the Task Scheduler job.
