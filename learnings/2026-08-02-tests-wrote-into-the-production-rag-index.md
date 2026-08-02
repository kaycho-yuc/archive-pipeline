# The test suite was writing fake notes into the production RAG index

**Problem (one line):** `pytest` injected four fixture notes (`메모.md`, `메일 - 김기봉.md`, `문서-계약서.pdf.md`, `문서-내역서.xlsx.md`) into the owner's live LanceDB index, where the Telegram bot and the MCP `search_vault` tool could cite them as real sources — and spent real embedding API calls doing it.

## Approach (plain steps)
1. Found it by accident, not by looking. While smoke-testing a new `project=미정` filter against the real index, the top two hits were `문서-계약서.pdf.md` with body text "내용 계약서.pdf" and summary "요약." — obviously fixture data. The lesson is in the noticing: a filter that returns *plausible-shaped* garbage is easy to read as success.
2. Checked whether those notes existed in the vault. They did not: `mcp_server._notes()` found 0 matching, so they were index-only ghosts.
3. Quantified before theorizing: 232 vault notes vs 236 indexed, 4 ghosts / 4 chunks.
4. Traced the write path rather than guessing which test did it. `pipeline.process_file` → `_index_note_best_effort` → lazy `import rag_local` → `rag_local.index_note`. `tests/test_pipeline.py` mocks `extract_text`, `classify` and `notifier`, but never `rag_local`, and `rag_local.DB_PATH` resolves to the production index. Matching the ghost names against the test fixtures confirmed it line by line.
5. Re-measured mid-investigation and the ghosts were gone (2032 → 2028). Did not treat that as "no bug": the watcher runs `rag_local.ingest(reset=False)` hourly and its prune step removes notes missing from the vault. So the defect is real but self-healing, with an exposure window of up to an hour. That reframed the severity honestly instead of in either direction.
6. Checked whether any test asserts indexing happens before disabling it. None did, so the guard costs no coverage.
7. Verified the guard by removing it. With `tests/conftest.py` renamed away and `RAG_DB_PATH` pointed at a throwaway directory, the new regression test failed with a traceback reaching `rag_local.py:380 db.table_names()`, and a `vault.lance` appeared in the throwaway path. That proves the test fails for the right reason and the write really went where it was aimed.

## Judgment calls (what was NOT done, and why)
- Did **not** fix it by adding a `rag_local` mock to `test_pipeline.py`. The failure mode is *forgetting* to mock; a per-file fix leaves the next test author with the same trap. An `autouse` fixture in `conftest.py` cannot be forgotten.
- Did **not** import `rag_local` inside `conftest.py` to patch it directly. That pulls in lancedb (~10s per session) and there is already a test guarding that cost. The fixture only patches the module if `sys.modules` already holds it, and otherwise relies on the env vars.
- Did **not** rely on `RAG_DB_PATH` alone. `DB_PATH` is computed at import time, so the env var is useless once the module is loaded — both mechanisms are needed for different orderings.
- Did **not** clean the index. It had already self-healed, and running a prune to "fix" an absent problem would have muddied the before/after baseline the verification depended on.
- Did **not** accept the passing regression test on its own. A test that would pass with the fix removed proves nothing.

## Reusable rules
**When a query against production data returns results shaped like your test fixtures, stop and check whether they *are* your test fixtures.** Plausible-looking output is the easiest kind to mistake for a working feature.

**Any test that exercises a code path with a lazy import of a stateful client can reach production state.** Mocking the obvious collaborators (`extract`, `classify`, `notify`) is not enough — trace what the function under test imports *inside* itself.

**Prove an isolation guard by removing it and watching the test fail.** Isolation fixtures are invisible when they work, so the only evidence they work is a failure when they are gone.
