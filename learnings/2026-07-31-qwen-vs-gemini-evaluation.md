# Can Qwen replace Gemini across all four cloud seams? (research, no code)

**Problem (one line):** The pipeline depends on Gemini at four independent call sites; the
question was whether Qwen (Alibaba Model Studio) could take all four, for cost, Korean
quality, open-weight self-hosting, and vendor independence.

**Answer:** Yes for all four, but the confidence differs sharply per seam. Nothing was changed
in this session — this is the decision record so the swap can be executed later without
re-deriving the research.

## The four seams and what a swap actually costs

| Seam | Code | Env switch | Gemini today | Gemini-only coupling to replace |
|---|---|---|---|---|
| Classifier | `classify._call_gemini` | `LLM_PROVIDER` | `gemini-3.1-flash-lite` | `response_mime_type`, `ThinkingConfig` |
| Scan OCR | `extract._gemini_ocr` | `OCR_PROVIDER` | `gemini-3.5-flash-lite` | `Part.from_bytes`, `candidates[0].finish_reason == MAX_TOKENS` |
| RAG embeddings | `rag_local._embed_gemini` | `RAG_EMBED_PROVIDER` | `gemini-embedding-001`, 3072-dim | `EmbedContentConfig(task_type=...)`, 100/request batch |
| RAG answers | `rag_local._generate` | `RAG_GEN_PROVIDER` | `gemini-3.1-flash-lite` | `ThinkingConfig`, 503 retry loop |

Each seam is already a clean data-in/data-out boundary with an env-keyed dispatcher, so adding
a provider is a sibling function plus one `elif` — exactly the shape the
`2026-07-15-gemini-backend-for-mac.md` rule predicts. `_gemini_client()` is duplicated verbatim
in three modules; a Qwen client would be duplicated the same way rather than refactored, to keep
the diff surgical.

The embedding dimension is baked into the LanceDB Arrow schema (`rag_local.py` `_ensure_table`),
so the embedding seam is the only one whose swap costs a full `--reset` re-index on n100
(measured baseline: 251 notes / 2172 chunks / 165s).

## Model landscape as of 2026-07-31

Prices are per 1M tokens, input/output. Recheck these before acting; they move.

**Gemini (incumbent)**
- `gemini-3.1-flash-lite` — GA 2026-05-07, $0.25/$1.50, no shutdown date announced.
- `gemini-3.5-flash` — $1.50/$9.00. Already rejected here (503 on 4/4 attempts).
- `gemini-embedding-001` — 3072-dim, MRL-truncatable, $0.15.
- `gemini-embedding-2-preview` — multimodal, since 2026-03-10. Its embedding space is
  **incompatible** with 001, so it is a re-index either way.
- 2.0 Flash / Flash-Lite shut down 2026-06-01; the 2.5 family retires 2026-10-16. The current
  3.1 pin is not under time pressure.

**Qwen (candidate).** Endpoint `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`,
OpenAI-compatible, Singapore region carries the full lineup. So the swap uses the `openai`
client, not a second vendor SDK.

| Role | Model | Price | Notes |
|---|---|---|---|
| Classifier / RAG answers | `qwen-flash` | $0.05/$0.40 | 5x cheaper in, 3.75x out. `response_format={"type":"json_object"}` supported. |
| Fallback if flash fails the A/B | `qwen-plus` | $0.40/$1.20 | |
| Frontier (not needed here) | `qwen3.7-max` | $1.20-3.00/$6.00-15.00 | 2026-05-19, 1M context, GPQA-D 92.4 |
| OCR | `qwen3-vl-plus` | $0.20/$1.60 | Structured output, skew handling, table-to-HTML, bbox |
| OCR (transcription only) | `qwen-vl-ocr` | $0.07/$0.16 | Does **not** follow prompts; not a drop-in for `GEMINI_OCR_PROMPT` |
| Embeddings | `text-embedding-v4` | $0.07 | Qwen3-Embedding. Dims 64…2048 (default 1024). 100+ languages, 8192-token input. |

Newest generation on the model list is `qwen3.7-max` / `qwen3.7-plus` / `qwen3.6-flash`;
`qwen-flash` / `qwen-plus` are rolling aliases onto those. Prefer the aliases so the pipeline
does not need re-pinning every quarter — with the caveat in the classifier section below.

## Per-seam verdict

**1. RAG embeddings — lowest risk, clearest win.** Half the price, and `text-embedding-v4` is
Qwen3-Embedding, which led MTEB-multilingual. Korean recall should be at least bge-m3 class,
since both are multilingual-first unlike Gemini's English-leaning tuning. Set `RAG_EMBED_DIM`
to 2048 (or 1024 to halve storage) and `--reset`. The existing dimension guard in
`rag_local.embed` already fails loudly on a misconfigured swap.
**Trap:** Qwen's batch cap is **10 texts per call**, not Gemini's 100. Reusing
`GEMINI_EMBED_BATCH=100` would break the swap; 2172 chunks becomes ~218 requests, not ~22.

**2. RAG answers — low risk, big cost win.** The load-bearing detail is the thinking cap. The
`thinking_level="minimal"` setting that took answers from 37-119s down to 2.1-2.6s maps to
`extra_body={"chat_template_kwargs": {"enable_thinking": False}}` on the OpenAI-compatible
endpoint. Miss it and the two-minute-answer regression returns. Some newer Qwen3-Instruct
builds are non-thinking by default and ignore the flag; verify empirically rather than assume.
Also note the older bot benchmark finding that thinking models put output in
`reasoning_content` and leave `content` empty — same failure class, different layer.

**3. Classifier — medium risk, needs the same A/B that picked 3.1 over 3.5.**
`response_format={"type":"json_object"}` replaces `response_mime_type`. The risk is precisely
the failure recorded for `gemini-3.5-flash-lite`: categories emitted outside the controlled
`DOC_TYPES` vocabulary at temperature 0, which fragments vault filenames. That is a
model-behavior property, not a provider property, so Qwen earns nothing from Gemini's testing.
Re-run the same protocol: 10 runs, temp 0, real documents, assert every emitted category is
in-vocabulary. **This is also why the rolling-alias preference does not apply here** — an alias
that silently rolls `qwen-flash` onto a new generation would re-run that risk without a test.
Pin the classifier to an explicit version.
Additionally, Qwen thinking-mode models can return not-strictly-valid JSON even with
`json_object` set, so keep thinking off and keep the existing JSON repair path.

**4. Scan OCR — highest risk, do it last.** This seam has a concrete accuracy scar: EasyOCR and
PaddleOCR misread `685-317` as `685-377`, and Gemini vision was adopted because it transcribed
every critical value exactly. Qwen3-VL reads well on paper, and paper is not the bar. Gate on
re-running the same 대수선 필증 fixture and comparing lot number, area, amount, date, and
company name character by character. `qwen3-vl-plus` is the like-for-like swap; `qwen-vl-ocr`
is cheaper but instruction-blind. Reimplement the truncation guard as
`choices[0].finish_reason == "length"`. Keep sending un-binarized renders.

## The open-weight argument (the one Gemini cannot answer)

Qwen3-Embedding (0.6B/4B/8B), Qwen3-VL, and the Qwen3 instruct models are open-weight and run
under Ollama or vLLM. The cloud API and the RTX 4080 box could therefore run the *same model
family*, keeping the embedding space compatible between the cloud path and a future local path.
Under Gemini those are disjoint worlds and every move between them costs a full re-index.
Concretely, `qwen3-embedding` is on Ollama today, which turns `RAG_EMBED_PROVIDER=ollama` into
a genuine fallback instead of a different system with a different index.

## Recommended execution shape (when this is picked up)

Add `qwen` as a **third** provider, do not replace Gemini. It preserves the working n100 setup
during evaluation, it is what makes the classifier and OCR A/Bs possible at all, and it costs
one `elif` per dispatcher. Remove Gemini only after all four A/Bs pass.

Order, cheapest and safest first:
1. `rag_local.py` embeddings + answers. Verify by `--reset` on n100, then a fixed set of Korean
   questions through the bot, compared against the recorded Gemini baseline for both answer
   content and wall-clock.
2. `classifier/classify.py`. Verify by the 10-run temp-0 vocabulary check above.
3. `extractors/extract.py`. Verify by the 685-317 fixture, character-exact.

New config: `DASHSCOPE_API_KEY`, `QWEN_BASE_URL`, and `qwen` as an accepted value for the four
existing provider switches. Add `openai` to `pyproject.toml`. Existing tests already mock at
these dispatcher boundaries, so extend them rather than rewriting.

## Blockers to clear before writing code

- **Billing.** DashScope international needs an Alibaba Cloud account with a payment method.
  Free quota is 1M tokens per model for 90 days, which covers the whole evaluation. Same trap
  as the Google one: a consumer Qwen chat subscription does not grant API access. Confirm the
  **API billing tier**, never a consumer plan.
- **Data residency.** Vault content would go to Alibaba Cloud Singapore instead of Google.
  Private vault, owner's call, but it should be a deliberate one.
- **Config drift on the Mac.** `.env` there still pins the superseded
  `gemini-3.1-flash-lite-preview` and has no `OCR_PROVIDER` / `RAG_EMBED_PROVIDER` /
  `RAG_GEN_PROVIDER` keys, so only the classifier runs on Gemini there. n100 is the machine
  running all four. Fix the stale pin before treating the Mac as any kind of baseline.

## Reusable rule

When evaluating a provider swap, price and benchmarks are the easy half; the hard half is
enumerating the **behavioral guarantees the current provider is quietly supplying**. Here that
was four of them: a thinking cap that keeps a bot conversational, a controlled-vocabulary
instruction-following property proven only by A/B, a per-request batch limit the batching code
was written against, and a character-exact OCR result on a specific fixture. None appear on a
pricing page, and each one is a distinct pre-flight test. Rank seams by which guarantee is
hardest to re-verify, then migrate in that order, cheapest guarantee first.

## Sources (2026-07-31)

- Gemini: [models](https://ai.google.dev/gemini-api/docs/models),
  [deprecations](https://ai.google.dev/gemini-api/docs/deprecations),
  [embeddings](https://ai.google.dev/gemini-api/docs/embeddings)
- Qwen: [supported models](https://www.alibabacloud.com/help/en/model-studio/models),
  [pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing),
  [text-embedding-v4](https://www.alibabacloud.com/help/en/model-studio/embedding),
  [structured output](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output),
  [deep thinking](https://www.alibabacloud.com/help/en/model-studio/deep-thinking)
