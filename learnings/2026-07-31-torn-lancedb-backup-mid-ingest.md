# A LanceDB backup taken mid-ingest is silently torn

**Problem (one line):** Backing up `rag_db/` before a destructive `--reset` produced a copy
whose row count did not match the source, and the mismatch looked like a broken copy.

## What actually happened

Three successive reads of the **source** table, minutes apart, returned 905, then 1588, then
2029 rows. The backup taken between the second and third read held 1588. The copy was faithful;
the source was moving. Lance versions were climbing 477 → 612 the whole time, because an ingest
kicked off by the day's dedupe migration (`migrate_dedupe_notes.py`, `vault_backup_*.zip`,
`run_watch.py` restarting) was still writing.

`cp -r` on a Lance dataset is not atomic. It snapshots whatever manifest and fragments exist at
the moment each file is read, so a copy started mid-write can land on a version that never
corresponded to a coherent committed state.

## The approach

1. **Do not assume the copy is the broken side.** Two numbers disagree; either could be wrong.
2. **Measure the source twice.** Read `count_rows()` and `version` from the live table, wait a
   few seconds, read again in the same process. Equal on both means quiet; different means the
   source is being written and nothing downstream is trustworthy yet.
3. **Find the writer before blaming the format.** `Get-CimInstance Win32_Process` filtered on
   `python` surfaced `run_watch.py`; its `watch.log` and the repo's recent file mtimes explained
   the ingest. Checking `_versions/` and `_deletions/` on both sides first was the wrong first
   move: it showed identical directory listings and pointed nowhere.
4. **Re-copy once stable, then verify both sides.** Compare `rows`, `version`, and vector
   dimension across source and backup. Identical on all three, or it is not a baseline.

## Judgment calls

- **Did not delete the torn copy and move on.** The row mismatch was the only evidence that a
  writer was active. Deleting it first would have destroyed the signal and left the real risk,
  a concurrent write during `--reset`, undiscovered.
- **Did not reach for Lance internals** (`_deletions/`, tombstones, compaction) even though a
  1588-vs-905 gap looks exactly like resurrected deleted rows. That hypothesis fit the numbers
  and was still wrong. Cheap external observation of the source beat plausible internal theory.
- **Did not stop the watcher to force quiet.** It runs the Telegram bot and inbox watcher on a
  production machine; the repo has `pause_ai.ps1` for this, and stopping a live service is the
  owner's call, not a debugging convenience.
- **Did not treat the recorded figure as the baseline.** The prior note had 251 notes / 2172
  chunks; this machine measured 235 / 2029 after the dedupe run. A baseline is measured now, on
  the machine under test, not quoted from a document.

  **Correction (added later, once the writer had stopped): 235 / 2029 was itself a moving
  reading.** The settled state is **231 notes / 2025 chunks** at Lance version 639, which matches
  the vault exactly (231 notes on disk, 0 orphans, 0 unindexed). So this bullet's own figure fell
  to the very trap the bullet warns about: it was taken while the dedupe migration's ingest was
  still committing. Quiet has to be *proven* before a number is worth writing down, not assumed
  because the previous read finished. Anyone using this note as a reference should measure again
  rather than trust either figure above.

## Reusable rule

Before copying any live datastore, prove it is quiet: sample its row count and version twice a
few seconds apart and require them equal. When a copy disagrees with its source, suspect the
source is moving before suspecting the copy is broken, and verify a backup by comparing
row count, version, and schema on both sides rather than by the fact that the copy command
exited zero.
