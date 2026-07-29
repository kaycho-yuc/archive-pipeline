# Numbers silently vanishing from a PDF: font subset glyphs in the Private Use Area

**Problem (one line):** The owner asked whether the pipeline was masking numbers — a recipe note's nutrition values and step numbers had all become invisible boxes, while the ingredient quantities on the same page were fine.

## Approach (plain steps)
1. Answered the literal question first by checking the code: nothing in the pipeline touches digits, so "masking" was ruled out before any theorizing.
2. Dumped the note's characters **with Unicode categories**, not just eyeballed them. The culprits were category `Co` (private use: `U+F639`–`U+F640`, `U+F6DC`), **not** the bidi/format controls the pasted symbol suggested. That single distinction identifies the cause: a subset font mapping glyphs into the PUA with no `ToUnicode` table, so the extractor returns raw glyph codes.
3. Measured the blast radius across the whole vault before designing anything: **2 of 269 notes**. Critically, the scarier-looking one (a 견적서, 98 occurrences) turned out to be one glyph repeated as a decorative rule, with all 253 digits and the amount intact. Only the recipe lost data.
4. That contrast handed over the discriminator: **count distinct PUA codepoints, not total.** Garbled body text uses many (9 here); decoration repeats one. Threshold 5.
5. Fixed at the existing seam: if embedded text looks garbled, fall through to the OCR path already in the module, which renders the page to an image so the font's encoding stops mattering. Also had to override the trailing `len(ocr) > len(embedded)` comparison — garbled text is *long*, so length is the wrong tiebreaker once you know it's junk.
6. Verified against the real PDF end to end, then via the live watcher.

## Judgment calls (what was NOT done, and why)
- Did **not** hand-patch the damaged note from my inferred glyph→digit mapping. Good thing: **the inference was wrong.** I read the step markers as a contiguous run and extrapolated `U+F639 = "1"`, ignoring evidence I already had that step 1 used a *different* code (`U+F6DC`). Truth was `U+F639 = "0"`. Cropping the page at 600 DPI and reading the pixels settled it — 4 of 6 values had agreed, which is exactly how a wrong mapping hides.
- Did **not** build a general PUA→Unicode decoder. The mapping is per-font and per-document; the only sound reader is the rendered pixels.
- Did **not** trigger on *any* PUA character. That would have sent a healthy 견적서 through a full document OCR for a decorative line.
- Did **not** delete the original damaged note; reprocessed the source instead and left removal to the owner.

## The operational trap that cost a cycle
The fix was green in tests while the **live watcher kept emitting the broken output** — a Windows Scheduled Task holds the code it imported at startup. The tell was in the log: only one HTTP call (classifier), none to the vision model. **After editing pipeline code, restart the task**, then confirm the new log lines actually appear.

## Reusable rule
When characters go missing from extracted text, **classify the survivors by Unicode category before theorizing** — `Co` means the extractor handed back font-internal glyph IDs and the text layer is unusable, so re-read from pixels rather than trying to decode it. And when you infer an encoding from a pattern, **check it against ground truth before acting on it**: a mapping that explains most of the data is the normal appearance of a wrong mapping.
