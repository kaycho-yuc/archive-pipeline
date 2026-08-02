# A silent default makes a field look 100% complete while being 31% wrong

**Problem (one line):** Work notes all carried a `project:` value, so the field measured as 0% missing — but 60 of 192 had been filled by a silent fallback rather than by detection, and some were provably the wrong site.

## Approach (plain steps)
1. Located where the value actually comes from before believing the "hardcoded" framing. `detect_project()` was already deterministic (a registry of 지번 identifiers from `.env`, matched against filename then body) — nothing was hardcoded in code. The defect was one line downstream: `notes/write_note.py` did `result.project or DEFAULT_WORK_PROJECT`.
2. Re-ran detection over the existing 192 notes to separate *detected* from *defaulted*. 132 vs 60. The 0%-missing figure I had reported earlier was true and useless: the field is never missing precisely because it is always forced.
3. Sampled the 60 and found real errors, not just unknowns — a `성수동2가 314-38` document and an `아차산로 90` document, both labelled `성수동 리모델링`. That turned "imprecise" into "wrong", which justifies the change.
4. Split the fix by what each part can be trusted to know:
   - deterministic registry match → may set `project`
   - LLM → may only report what string it saw (`site`), never set `project`
   - neither → write `미정` and notify, so a human decides later
5. Measured the registry improvement — and got **191/192**, which was nonsense. The notes already contain `project: 성수동 리모델링` in their own frontmatter, so adding that phrase as an identifier meant the scan was reading back the label it had written. Re-measured against the `## 원문` body only: **164/192**. The production path never has this problem (it scans extracted document text, not the note), so the bug was in the measurement, not the code.
6. Traced every other caller of the changed function. `migrate_revise_notes.py` promised in its docstring that it "preserves project" but never implemented it — the upstream fallback had been coincidentally refilling the same value. Removing the fallback would have made that script overwrite human-confirmed projects with `미정`.

## Judgment calls (what was NOT done, and why)
- Did **not** let the LLM's `site` string become the `project` value. It is only ever an input to `detect_project`. A test asserts specifically that an unregistered site does not leak through — that is the whole point of the field.
- Did **not** add bare `성수동` to the identifier list, even though it would have "fixed" 14 more notes. A different site (`성수동2가 314-38`) would match it. A silent default was being replaced; a sloppy identifier would just reintroduce it.
- Did **not** build an interactive prompt in the watcher. It runs unattended; the owner chose notify-now / reconcile-later, so no pending-state store was needed.
- Did **not** emit `site:` on every note. Only when `project` is `미정`, because that is the only case where anyone needs it.
- Did **not** touch `rag_local.py` — a concurrent session owned that file. Staged only this session's eight files and left the other five in the working tree.
- Did **not** keep `getattr(result, "site", "")`. `site` is a dataclass field with a default; guarding for its absence is defending against something that cannot happen.

## Reusable rules
**A completeness metric measured downstream of a fallback measures the fallback, not the data.** Before reporting "N% missing", check whether anything upstream fills the field unconditionally — if so, re-derive the value from the raw input and compare.

**When a corpus has been labelled by the rule you are now testing, do not test the rule against that corpus.** Adding the label's own text as a detection key turns the measurement circular. Strip the generated metadata and measure against the original input.

**A docstring promise that no code implements can survive indefinitely if an unrelated default happens to produce the same result.** When removing a default, grep every caller of the code path it fed and check whether any of them were quietly relying on it.
