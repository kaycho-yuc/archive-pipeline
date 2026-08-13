# An empty glob became a delete-everything instruction

**Problem (one line):** A cosmetic report ("this file hardcodes `C:\Users\OWNER\...`, but the user
is `Indion`") turned out to sit on top of a latent bug: if that path is ever wrong, `ingest()`
deletes the entire RAG index without raising anything.

## The approach

1. **Confirm the report before acting on it.** Both line numbers were accurate, but the two sites
   were not the same kind of problem. `ingest_vault.py:30` is a genuine hardcode that is
   **unreachable** — its `VAULT` is used only on the retired `openwebui` branch, and the default
   `local` backend returns before touching it. `rag_local.py:63` is not a hardcode at all; it is a
   *fallback* after `os.getenv(...)`. On this machine `.env` supplies the real path, so nothing was
   broken. Reporting "fixed 2 hardcoded paths" would have been the wrong answer to the wrong bug.

2. **Ask what happens when the fallback is used, not whether it is pretty.** The `OWNER` folder
   does not exist. So: what does the code do with a vault path that does not exist?

3. **Trace the bad value to its consumer.** `list_notes()` calls `rglob` on the missing folder.
   Verified in a one-liner rather than assumed: `rglob` on a nonexistent directory returns `[]` and
   raises nothing. That empty list flows into the orphan-pruning step:

   ```python
   current = {n.name for n in notes}          # empty
   for stale in sorted(set(existing) - current):
       tbl.delete(...)                        # every row
   ```

   A misconfigured path is therefore read as "the user deleted all 244 notes." 1,989 chunks gone,
   exit code 0, no error printed. The pruning code was mine, added for a good reason (ghost notes
   being cited as sources). The defect is that it trusts an unvalidated input.

4. **Put the guard where the damage happens, not where it is convenient.** Two checks:
   `VAULT.is_dir()` runs **before** `connect(reset=reset)`, because `--reset` empties the table on
   connect and a check after that point protects nothing. The second check (index has rows, vault
   yields none) catches the subtler case where the path exists but `INCLUDE_DIRS` no longer matches.

5. **Assert on the survivor, not the exception.** Both new tests assert `count_rows()` is unchanged
   after the failure, not merely that `RuntimeError` was raised. A guard that raises *after*
   deleting would pass an exception-only test.

## The judgment calls

- **Did not change the fallback to `Indion`.** That fixes this machine and reproduces the bug on
  the next one. Replaced it with the OS-aware `os.getenv` chain `mcp_server.py` already used, which
  also removed a second way of resolving the same path in one repo.
- **Did not raise at import time** when the env var is missing. `rag_local` is imported by the MCP
  server, the pipeline, and the tests; a module-level raise turns a config problem into an
  everything-is-down problem. The check belongs in the one function that destroys data.
- **Did not guard `--reset` against ending with an empty index.** It is explicitly destructive and
  the vault is the source of truth, so the cost is one re-index, not lost data.
- **Left `OWNER` in `README.md` and `SYSTEM-HANDOFF.md`.** Those are configuration examples. Fixed
  `.claude/skills/my-vault/SKILL.md:13`, which was wrong in the folder structure too and is read as
  fact by a skill.

## The reusable rule

**A search that finds nothing and an error are different events — never let the first one reach a
delete step.** When a scan (`glob`, `rglob`, `listdir`, a query) feeds a diff-and-delete, ask what
that scan returns when its input is wrong. If the answer is "empty, silently," the delete needs a
precondition check on the input, placed before the first irreversible operation, and tested by
asserting the data still exists.

Related: [[2026-08-02-verify-filter-before-schema-migration]] (test the risky mechanism before
paying for the migration), [[2026-08-02-silent-default-fakes-metadata-completeness]] (a silent
default hiding a real gap).
