# Contract G1 — Data Gateway: data classes A/B/C + PII masking before any external LLM

Spec: `docs/design/LawVN-v1.1.md` §4 (and `docs/design/v1.1-gap.md` item G1). Read `AGENTS.md` first. Do not commit.
Rule of the design: classify the data first, then choose the model; PII is masked BEFORE the router; the mapping
(real value ↔ placeholder) never leaves the process; class A never goes to an external LLM.

## Files you may create or edit (nothing else)
- `backend/app/gateway/__init__.py`, `backend/app/gateway/pii.py`, `backend/app/gateway/classify.py` (new)
- `backend/app/agent/pipeline.py` (wrap `run_chat`, see below)
- `backend/app/api/routes.py` (one new route at the end, section `# ---------- Data Gateway ----------`)
- `backend/tests/test_gateway_pii.py` (new)

## `gateway/pii.py`
```python
@dataclass
class Masked:
    text: str                      # masked text
    mapping: dict[str, str]        # placeholder -> original (kept in memory only)
    counts: dict[str, int]         # entity type -> number of distinct values

def mask(text: str, *, mapping: dict[str, str] | None = None) -> Masked: ...  # reuse/extend a mapping (history)
def unmask(text: str, mapping: dict[str, str]) -> str: ...
```
Entity types and placeholders (Vietnamese labels, numbered per type, same value → same placeholder):
`[CCCD_n]` 12-digit citizen ID or 9-digit CMND (standalone digit runs, also with spaces/dots every 3 digits);
`[SĐT_n]` VN phone (`0` or `+84`/`84` then 9 digits, spaces/dots/dashes allowed); `[EMAIL_n]`;
`[STK_n]` bank account: 8–16 digits right after "STK", "số tài khoản", "tài khoản số", "TK" (case-insensitive);
`[TIỀN_n]` money amounts with a currency marker: "12.000.000 đồng", "12,5 triệu", "15 triệu đồng", "5.000.000đ", "VND";
`[TÊN_n]` person names: 1–4 capitalised Vietnamese words after a title word (ông, bà, anh, chị, em, cô, chú, Ông, Bà,
Anh, Chị, Mr, Mrs, Ms) or after "họ tên:", "họ và tên:", "người lao động:", "tên tôi là", "tôi là"; do not treat common
sentence words as names (keep a small stoplist, e.g. "Công", "Tòa", "Nhà", "Bộ", "Điều", "Khoản", "Luật");
`[ĐỊA_CHỈ_n]` address text after "địa chỉ:", "trú tại", "thường trú", "cư trú tại", "ở số", up to the end of the line or
the next ";" / "." that ends the clause.
Must NOT mask: law citations ("Điều 36", "khoản 1 Điều 35", "điểm a"), document numbers ("45/2019/QH14",
"145/2020/NĐ-CP", "05/2016/QĐNV-KD"), dates ("25/11/2016", "ngày 01 tháng 10 năm 2023"), years, counts of days/months
("30 ngày", "02 tháng tiền lương"), article numbers. Unmasking restores the exact original string.

## `gateway/classify.py`
`classify(text: str, *, source: str = "chat") -> str`: `"A"` when `source == "upload"` (client files, design §8);
`"B"` when `mask(text).counts` is non-empty (personal data present, sent out only masked); otherwise `"C"`.
`gate(message: str, history: list[dict] | None = None, *, source: str = "chat") -> GateResult` with fields
`data_class`, `message` (masked), `history` (masked copies, same mapping), `mapping`, `counts`.
Class A must raise `PermissionError("class A must not reach an external LLM")` when passed to `gate`, because only the
upload path produces A and it never calls an LLM.

## Integration (`agent/pipeline.py`)
In `run_chat`, before anything that can reach an LLM (guard classify, answer, issue split, rewrite, the M0 fallback, pv
mode): `g = gate(message, history)`; run the existing logic with `g.message` / `g.history`; wrap the yielded events so
every string value inside `data` (recursively in dicts/lists: token text, section title/detail, suggest_rewrite
original/suggested/reason, citation display/text) is passed through `unmask(…, g.mapping)` before it reaches the client.
Log only `g.data_class` and `g.counts` (never the mapping or originals). Retrieval runs on the masked text too.
Keep the injection check on the ORIGINAL message (it is local, no LLM).

## Route
`POST /api/gateway/preview` body `{"text": str}` → `{"data_class", "masked", "counts"}` (no originals in the response).
For testers to see what would leave the system.

## Tests (`tests/test_gateway_pii.py`, pure, no DB/LLM)
1. A synthetic paragraph with every entity type (fake values only, e.g. "ông Nguyễn Văn Thử, CCCD 001203004567, SĐT
   0912 345 678, email thu.nv@example.com, STK 1903 4567 8901 23 tại Techcombank, lương 12.500.000 đồng, trú tại số 12
   ngõ 34 phố Mẫu, phường An Bình, quận Thử, Hà Nội"): after `mask`, none of the original values appears (substring
   check, ignoring spaces), every type is counted, and `unmask(masked) == original`.
2. Same value twice → same placeholder; two different names → `[TÊN_1]`, `[TÊN_2]`.
3. Legal text that must stay unchanged: "Theo khoản 1 Điều 36 Bộ luật Lao động số 45/2019/QH14 và Nghị định
   145/2020/NĐ-CP, người lao động được báo trước 30 ngày; Quyết định số 05/2016/QĐNV-KD ngày 25/11/2016 bồi thường
   02 tháng tiền lương." → `mask(...).text == input` and `counts == {}`.
4. `classify`: plain legal question → "C"; question with a phone number → "B"; `source="upload"` → "A"; `gate` on class A
   raises `PermissionError`.
5. `run_chat` integration with a fake router (monkeypatch `app.agent.pipeline.get_router` and the qa module's
   `get_router` to an object that records every `messages` it receives and returns a fixed answer containing a
   placeholder): no recorded message contains the fake phone/CCCD/name; the events the user receives contain the
   original name again (unmasked). Use the M0 path (monkeypatch `_data_loaded` to return False) so no DB is needed.
6. API: `POST /api/gateway/preview` returns `data_class == "B"` and masked text without the fake CCCD.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_gateway_pii.py
docker compose exec -T api python -m pytest -q -m "not llm"          # 192 passed baseline must stay green
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/gateway app/agent/pipeline.py app/api/routes.py tests/test_gateway_pii.py
```
Also run, and report the number: masking the whole law corpus must not touch citations —
`docker compose exec -T api python -c "from app.db.base import SessionLocal; from sqlalchemy import text; from app.gateway.pii import mask; db=SessionLocal(); rows=[r[0] for r in db.execute(text(\"select text from legal_node where doc_id in ('blld2019','blld2012','nd145_2020')\"))]; c={}; [c.__setitem__(k, c.get(k,0)+v) for t in rows for k,v in mask(t).counts.items()]; print(len(rows), c)"`
Target: CCCD, SĐT, EMAIL, STK, TÊN and ĐỊA_CHỈ counts 0 (TIỀN may be > 0 because laws mention amounts; report it).
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
