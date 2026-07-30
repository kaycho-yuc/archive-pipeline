# Files stranded in an iCloud `_inbox`: rename across the cloud boundary, not slow I/O

**Problem (one line):** The pipeline wrote notes correctly but never archived the originals — every move died on `파일 이동 시간 초과(20s)`, so the same files were retried forever on each sweep.

## Approach (plain steps)
1. Checked state before theorizing: notes existed (267→269), hashes were recorded, originals still in `_inbox`, `_archive` empty. That located the failure at exactly one step (`_move_to`) and proved no data was at risk — the hash log makes a retry idempotent.
2. Refused the obvious reading. "iCloud is slow" was already the code's own assumption (`MOVE_TIMEOUT`, hydration guard), and the file was **pinned**, not dehydrated (`attrs=0x00080020`), so the existing explanation did not fit.
3. Decomposed `shutil.move` into its primitive steps and timed each one separately against the real path: `read` 0.00s, `copy2` to another folder 0.00s, `os.rename` *within* `_inbox` 0.00s, `os.rename` **out of the iCloud root** → 60.01s then `OSError WinError 426` (`ERROR_CLOUD_FILE_REQUEST_TIMEOUT`). One probe isolated the culprit to a single syscall crossing a single boundary.
4. Read the failure with the timeout guard in mind: `shutil.move` *does* fall back to copy+unlink when rename raises, but only after the 60s stall — and the pipeline's 20s watchdog kills the worker first. Two individually reasonable mechanisms combined into a permanent stall.
5. Verified the replacement before proposing it, on a throwaway file written into the real `_inbox`: `copy2` + `unlink` across the same boundary = 0.02s.

## Judgment calls (what was NOT done, and why)
- Did **not** raise `MOVE_TIMEOUT` past 60s. Rename fails regardless; that only buys the same fallback at 60s per file.
- Did **not** remove the threaded timeout guard. It still earns its place for genuinely dehydrated files where the copy must trigger a download.
- Did **not** gate the fix behind a "is this path cloud-synced?" check. Detecting cloud roots is fragile, and copy+unlink is correct everywhere.
- Did **not** test on the owner's real documents. Probes used a throwaway file and restored every rename.
- Flagged that `_move_to` is shared code reaching the other machine, rather than treating a local discovery as a local fix.
- Moved the test's mock from `shutil.move` to `shutil.copy2` — the mock has to sit on the call boundary that now exists.

## Correction found in review (same day)
The first version of this fix copied straight to the final archive path, and I justified the lost
atomicity as "the hash log absorbs it." **That was wrong**, and a review caught it. The hash log
absorbs a crash *between* copy and unlink; it makes a crash *during* the copy worse. `shutil.copy2`
writes directly to the destination, so a kill mid-copy leaves a truncated file at the canonical
name with the source still in `_inbox` — and on the next sweep the hash matches, the duplicate
branch re-archives, the collision counter bumps the name, and the **intact** original lands as
`foo-1.pdf` while the truncated one keeps `foo.pdf`. Logged as a harmless 중복. Fixed by copying to
`<name>.part` and `os.replace`-ing it into position: that rename stays inside the archive folder,
never crosses the cloud boundary, and is atomic, so the final name only ever holds a complete file.

Lesson inside the lesson: when you trade away a property (atomicity), name the exact failure the
compensating mechanism covers, and check the adjacent ones it does not. "The log handles it" was a
claim about a different crash window than the one the change actually opened.

## Reusable rule
When an operation "hangs" on a synced/virtual filesystem (iCloud, OneDrive, Dropbox, network redirector), **time each primitive separately against the real path instead of trusting the composite call** — and check whether a watchdog is firing *before* a library's own fallback can run. Same-volume `st_dev` does not mean rename is legal: a cloud filter driver can veto crossing its root. Prefer copy+delete over rename across any sync boundary.
