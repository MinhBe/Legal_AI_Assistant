# Contract ML1 — questions in English / Japanese / Chinese, answered in the user's language

Spec: gap item ML1 (`docs/design/v1.1-gap.md`). Read `AGENTS.md` first. Do not commit. Never read `.env`.
Measured: retrieval already works for EN/JA/ZH (multilingual embedding); what fails is the classifier
(`out_of_corpus`), Vietnamese-only answers and the Han/kana filter in `llm/router.py`.

## Files you may create or edit (nothing else)
- `backend/app/agent/lang.py` (new)
- `backend/app/llm/context.py` (add an `answer_lang` ContextVar beside `data_class`, same pattern)
- `backend/app/llm/router.py` (only the two Han/kana checks)
- `backend/app/agent/pipeline.py` (set the language per step, the same way `data_class_scope` is set)
- `backend/app/agent/guard.py` (only `CLASSIFY_SYSTEM`: one sentence)
- `backend/app/agent/qa.py` (prompt line + `language` in the `done` payload)
- `backend/app/agent/verifier.py` (skip the quote check when the answer language is not vi)
- `backend/tests/test_lang.py` (new)

## `agent/lang.py`
- `detect(text) -> "vi" | "en" | "ja" | "zh"` pure heuristic, no packages: any hiragana/katakana → `ja`; Han
  characters (no kana) making up ≥ 20 % of letters → `zh`; Vietnamese-specific letters (`ăâđêôơư` and tone marks,
  use `guard.vi_diacritic_ratio`) ratio ≥ 0.03 → `vi`; mostly ASCII letters → `en`; default `vi`.
- `NAMES = {"vi": "tiếng Việt", "en": "tiếng Anh", "ja": "tiếng Nhật", "zh": "tiếng Trung"}`.
- `answer_instruction(lang) -> str`: "" for vi; otherwise a Vietnamese instruction: "Viết `summary` và `detail`
  của mọi mục bằng {NAMES[lang]}. Giữ nguyên số điều/khoản và tên văn bản tiếng Việt (ví dụ «Điều 25 Bộ luật Lao
  động 2019») rồi dịch ngắn trong ngoặc."

## Wiring
- `context.py`: `current_answer_lang` ContextVar default "vi", `answer_lang_scope(lang)`, `get_answer_lang()`.
- `pipeline.run_chat`: `lang = detect(message)` on the ORIGINAL message (before masking); wrap every `next(it)` in
  both scopes (`data_class_scope` and `answer_lang_scope`), exactly like the existing data-class loop. Log
  `"Ngôn ngữ câu hỏi: {lang}"`.
- `qa._answer_messages`: append `answer_instruction(get_answer_lang())` as one extra line right before
  "Trả về đúng JSON theo quy tắc." (system prompt unchanged). Add `"language": lang` to every `done` payload of
  `answer_with_citations`.
- `guard.CLASSIFY_SYSTEM`: add "Câu hỏi có thể viết bằng tiếng Anh, Nhật hoặc Trung: ngôn ngữ KHÔNG phải lý do để
  xếp out_of_corpus; xét nội dung như câu tiếng Việt."
- `router.py`: both `_CJK` rejections apply only when `get_answer_lang() not in ("ja", "zh")`; Hangul is still
  rejected (no Korean support). Keep behaviour identical for vi/en.
- `verifier.verify`: when `get_answer_lang() != "vi"`, skip the `quotes` check (a translation cannot be verbatim);
  existence and in-force checks stay.

## Tests (`tests/test_lang.py`, fakes only)
1. `detect` table, clear cases only: Vietnamese with diacritics, English, Japanese (kana), Chinese (Han only),
   Vietnamese containing a law number such as "145/2020/NĐ-CP".
2. `answer_instruction`: empty for vi, mentions the language name otherwise.
3. Router: with `answer_lang_scope("ja")` a fake cloud reply in Japanese is accepted; with "vi" it is rejected;
   Hangul is rejected in both.
4. `run_chat` with a Japanese question and a fake `_chat` recording `get_answer_lang()` at each step → "ja" at every
   step even when steps are resumed in fresh contexts (copy the pattern of
   `test_run_chat_keeps_level_when_resumed_in_fresh_contexts`).
5. `_answer_messages` contains the instruction for en and not for vi.
6. Verifier skips quotes for ja, still drops an out-of-force citation.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_lang.py tests/test_llm_tiers.py tests/test_verifier.py tests/test_guard.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/agent/lang.py app/llm app/agent/pipeline.py app/agent/guard.py app/agent/qa.py app/agent/verifier.py tests/test_lang.py
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
