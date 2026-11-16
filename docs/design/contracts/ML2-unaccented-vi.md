# Contract ML2 — unaccented Vietnamese: try both readings (VI and EN), keep the better match

Spec: gap item ML2 (`docs/design/v1.1-gap.md`). Minh: "mỗi khi gõ không dấu thì vừa đưa vào tiếng anh vừa đưa vào
tiếng việt để kiểm tra xem cái nào khớp hơn". Depends on ML1 (`app/agent/lang.py`, `answer_lang_scope`).
Read `AGENTS.md` first. Do not commit. Never read `.env`.

## Files you may create or edit (nothing else)
- `backend/app/agent/lang.py` (add the functions below)
- `backend/app/agent/pipeline.py` (decide the reading before `_chat`; pass the chosen text on)
- `backend/tests/test_lang_unaccented.py` (new)
- `frontend/lib/chat/types.ts`, `frontend/lib/chat/useChat.ts`, `frontend/components/chat/MessageList.tsx`,
  `frontend/app/globals.css` (only a small `.reading-*` chip)

## `agent/lang.py`
- `is_unaccented(text) -> bool`: letters are ASCII only (no Vietnamese diacritics, no CJK) and ≥ 3 words.
- `VI_SYLLABLES`: a frozenset of ~300 common unaccented Vietnamese syllables (toi, ban, la, cua, va, cho, khong, co,
  duoc, nguoi, lao, dong, hop, luong, viec, ngay, thang, nam, bao, nhieu, thoi, gian, thu, nghi, phep, cong, ty,
  sa, thai, cham, dut, tro, cap, bao, hiem, xa, hoi, ky, luat, quyen, nghia, vu, ... — enough to cover labour-law
  questions; keep it in the module, no external file).
- `vi_ratio(text) -> float`: share of word tokens (lower-case, alphabetic) found in `VI_SYLLABLES`.
- `restore_diacritics(router, text) -> str | None`: one `router.chat(..., task="route")` call (runs at the
  request's data class — called on the already masked text) with a short prompt: "Thêm dấu tiếng Việt cho câu sau,
  không đổi từ, không trả lời câu hỏi, chỉ trả về câu đã thêm dấu." Reject the result (return None) when it is
  empty, when `vi_diacritic_ratio` is still < 0.03, or when its word count differs from the input by more than 20 %.
- `choose_reading(router, search, text) -> dict`: only when `is_unaccented(text)`:
  - Reading EN = text as is. Reading VI = `restore_diacritics(...)` (fall back to the raw text when None).
  - `search(text_variant, top_k=5)` for both; score each reading = mean of the top-3 hit scores when hits carry a
    numeric `score`, else the number of hits; add `+0.15` to VI when `vi_ratio(text) ≥ 0.5` and `+0.15` to EN when
    `vi_ratio(text) < 0.2` (word evidence).
  - Return `{"lang": "vi"|"en"|"tie", "text": chosen text, "vi_text", "scores": {...}, "vi_ratio"}`; tie when the
    two scores differ by < 0.02 and the word evidence is neutral (0.2 ≤ vi_ratio < 0.5).

## `agent/pipeline.py`
- After `gate(...)`: if `detect(message)` is `en` and `is_unaccented(message)`, call `choose_reading` with the
  router and `search_nodes` (open/close a DB session). VI wins → continue with `vi_text` (still masked) and language
  `vi`; EN wins → language `en`; tie → yield one token "Bạn đang hỏi bằng tiếng Việt không dấu hay tiếng Anh? Bạn có
  thể gõ lại có dấu để mình trả lời chính xác hơn. / Is your question in English or unaccented Vietnamese?" and
  `done` with `{"category": "clarify_language"}`, no further LLM calls.
- Yield `("reading", {"lang", "vi_text", "scores"})` once before the answer starts (UI shows a chip "Đã hiểu là
  tiếng Việt: «…có dấu…»" or "Understood as English"). Log the scores.
- Injection check still runs on the ORIGINAL message (already the case) and also on `vi_text`.

## Tests (`tests/test_lang_unaccented.py`, fakes only)
1. `is_unaccented`: true for "thoi gian thu viec toi da", false for accented text, for CJK, for < 3 words.
2. `vi_ratio` high for "thoi gian thu viec toi da la bao lau", low for "what is the maximum probation period".
3. `restore_diacritics` rejects a bad model output (no diacritics / very different length) and accepts a good one.
4. `choose_reading` with a fake search (scores you choose): VI wins for a Vietnamese sentence, EN wins for an English
   one, tie when scores are equal and vi_ratio is neutral.
5. `run_chat` with a fake router/search and a fake `_chat` recording its message + `get_answer_lang()`: unaccented
   Vietnamese → `_chat` receives the restored text and language vi; English → unchanged text and en; tie → the
   clarify message and `done.category == "clarify_language"`, `_chat` not called.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_lang_unaccented.py tests/test_lang.py tests/test_llm_tiers.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/agent/lang.py app/agent/pipeline.py tests/test_lang_unaccented.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
