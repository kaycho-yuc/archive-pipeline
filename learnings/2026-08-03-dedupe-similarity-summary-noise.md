# A "same document?" similarity test was quietly grading the summarizer, not the document

**Problem (one line):** `migrate_dedupe_notes.py`'s same-source dedup gate (`SAME_SOURCE_FOLD_AT
= 0.90`) rejected 2 of 13 known-duplicate pairs (ratios 0.88) while accepting the rest (0.90-1.00),
and the accepted ones weren't even close to 1.00 despite the source docs being byte-identical.

## The approach

1. **Ran the change, measured, reported the actual numbers instead of the expected ones.** The
   task spec claimed "12 pairs at similarity 1.00." The real dry run produced 10 collapses, with
   ratios spread from 0.88 to 1.00. Rather than assume the spec's claim and adjust code to match
   it, the discrepancy was reported verbatim: exact ratios, which 2 pairs failed, by how much.
2. **Took the spread itself as the clue.** A genuinely identical source document should not
   produce a *range* of similarity scores across pairs — it should be near-constant. A spread
   that correlates with note length (shorter notes score lower) is the signature of the comparison
   including content that varies independently of the source, i.e. noise proportional to how much
   of the note *isn't* noise-free.
3. **Read the actual note files for one failing pair** rather than reasoning about the format
   abstractly. Both notes had `## 요약` (freshly written by the classifier each run) followed by
   `## 원문` (the extracted source text). Diffing the two note bodies by eye showed the `## 원문`
   sections were character-for-character identical; only `## 요약` differed.
4. **Measured before writing the fix**: compared `요약+원문` vs `원문`-only ratios for all 13
   pairs first, confirmed the signal became binary (12 pairs at exactly 1.0000, the true
   non-duplicate at 0.04-0.08) — then implemented, then re-measured on the real vault to confirm.

## Judgment calls

- **Did not touch `FOLD_AT` or `SAME_SOURCE_FOLD_AT`.** The thresholds were fine; the input being
  measured was wrong. Lowering a threshold to catch noisy data is a fudge that will eventually
  admit a false positive; fixing what's measured is not.
- **Did not special-case the failing pairs.** The fix is symmetric across all notes: extract
  `## 원문`, fall back to the whole body when the heading is absent (e.g. non-classifier notes
  like workout journals). No pair-specific logic.
- **Left the different-source path untouched.** Only the same-source branch (which already reads
  frontmatter to confirm `source_a == source_b`) switches to comparing `## 원문`; the general
  `FOLD_AT` check against full body text is unrelated and stayed as-is.

## Reusable rule

When a similarity/equality test over generated content gives a suspiciously wide or
length-correlated spread instead of a tight cluster, suspect that the compared text includes a
sub-part that is regenerated independently each time (a summary, a timestamp, an LLM restatement)
— diff two real, human-inspectable instances directly to find and exclude that sub-part, rather
than retuning the threshold that sits downstream of the measurement.
