# Contract I2 — code calculators by law version at the event date

Spec: `docs/design/LawVN-v1.1.md` §8; gap item I2. Depends on T2 (`resolve`, event date). Read `AGENTS.md` first.
Do not commit. Never read `.env`. Pure code, no LLM. Every result carries its legal basis and the label
"Kết quả tính tự động — cần luật sư đối chiếu" (examples are not lawyer-checked yet; see `docs/design/hau-kiem.md`).

## Files you may create or edit (nothing else)
- `backend/app/calc/__init__.py`, `backend/app/calc/labor.py` (new)
- `backend/app/api/routes.py` (new endpoints only)
- `backend/tests/test_calc.py` (new)
- `frontend/app/tinh/page.tsx` (new), `frontend/app/globals.css` (only new `.calc-*` rules),
  `frontend/app/layout.tsx` or the existing nav component (one nav link "Máy tính")

## Rules (pick the version by `event_date`: before 2021-01-01 → BLLĐ 2012, from 2021-01-01 → BLLĐ 2019)
Each function returns `{"value", "unit", "steps": [str], "basis": [{"doc_id", "node_id"?, "label"}], "version":
"blld2012"|"blld2019", "note"}`; `basis.node_id` only when that node exists in `legal_node` (look it up; omit if
missing). Inputs are validated (ValueError → HTTP 422 with a Vietnamese message).
1. `notice_days(contract_type, employer_side: bool, event_date, term_months=None)` — employer's unilateral
   termination notice (2019 Điều 36 k2; 2012 Điều 38 k2): indefinite term → 45 days; fixed term 12–36 months → 30
   days; under 12 months → 3 working days. Employee side (2019 Điều 35 k1; 2012 Điều 37): 45 / 30 / 3 working days
   for 2019 (indefinite / 12–36 months / under 12 months); for 2012 indefinite → 45 days, fixed term → 3 working
   days (note the 2012 rule depends on the reason — add a note "cần đối chiếu lý do theo Điều 37 BLLĐ 2012").
2. `service_years(start, end, unemployment_insured_months=0)` — working time for allowances: total months minus
   months with unemployment insurance; whole years plus remainder: 1–5 months → +0.5 year, ≥ 6 months → +1 year
   (NĐ 145/2020 Điều 8 k3 for 2019; same rounding for 2012 — note "theo NĐ 05/2015, cần đối chiếu").
3. `severance(avg_salary_6m, years)` — trợ cấp thôi việc: 0.5 × salary × years (2019 Điều 46; 2012 Điều 48).
4. `job_loss(avg_salary_6m, years)` — trợ cấp mất việc làm: 1 × salary × years, at least 2 × salary
   (2019 Điều 47; 2012 Điều 49).
5. `unlawful_dismissal(monthly_salary, days_not_working, notice_days_missing=0, daily_salary=None)` — employer's
   unlawful unilateral termination (2019 Điều 41 k1; 2012 Điều 42 k1): wages for the days not allowed to work +
   at least 2 months' wages + (if notice was breached) wages for the notice days missing; `daily_salary` defaults to
   monthly / 26 (note it is an assumption). Mention in `note` that insurance contributions and severance may also
   apply.
6. `limitation(discovered_on, dispute="individual")` — time limit to request settlement of an individual labour
   dispute: 1 year from the day the violation was discovered (2019 Điều 190 k1; 2012 Điều 202 k1); returns the
   deadline date and days left from today.
Use `decimal.Decimal` for money; round VND to whole đồng; format `steps` with thousands separators.

## API
- `POST /api/calc/{kind}` with kind in `notice`, `service-years`, `severance`, `job-loss`, `unlawful-dismissal`,
  `limitation`; JSON body = the function's arguments (dates ISO) plus `event_date` (default today); response = the
  result dict + `timeframe_version` from `resolve(...)["applicable"]`.

## Frontend `/tinh`
- Tabs for the six calculators, simple forms (VND inputs with thousands separators), a "Ngày sự kiện" field, result
  card with value, steps, basis chips (link `/api/law/{node_id}` when present), the version used, and the warning
  label above.

## Tests (`tests/test_calc.py`)
- Table tests for each rule and both versions, incl. boundaries: 11 vs 12 vs 36 vs 37 months; 5 vs 6 remainder
  months; job-loss minimum (1 year → 2 months); event dates 2020-12-31 vs 2021-01-01 switch the version; invalid
  inputs → ValueError; API returns 200 with `basis` and 422 on bad input.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_calc.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/calc app/api/routes.py tests/test_calc.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
