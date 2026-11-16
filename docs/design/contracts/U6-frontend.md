# Contract U6 — `/upload` page and graph link (Next.js 15, React 19, no new npm packages)

Plan: `docs/design/upload-ocr-kg-plan.md` (step U6). Read `AGENTS.md`, `frontend/app/dashboard/page.tsx` (style of a
client page that calls the API) and `frontend/app/graph/page.tsx` first. Do not commit. User-facing text in Vietnamese.

## Files you may create or edit (nothing else)
- `frontend/app/upload/page.tsx` (new, `"use client"`)
- `frontend/app/graph/page.tsx` (read `doc_id` from the URL)
- `frontend/components/Chat.tsx` (one nav link next to the existing graph link)
- `frontend/app/globals.css` (append a small `/* upload */` block only if needed)

## API (backend already done)
`API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"`.
`POST /api/uploads` (multipart `file`, optional `title`) → row; `GET /api/uploads` → rows; `PATCH /api/uploads/{id}`
`{"status": "approved" | "rejected"}`; `DELETE /api/uploads/{id}` (204). Row fields: `upload_id, doc_id, filename, mime,
size_bytes, pages, ocr_pages, chars, mean_ocr_conf, parse_mode, n_nodes, n_refs, data_class, status, error, preview,
created_at, duplicate?`. 413 / 415 / 422 carry `detail` text.
`GET /api/graph?doc_id=<doc_id>&uploads=1` → graph of one uploaded document.

## `/upload` page
- Header: title "Tải tài liệu lên", one line: "Tài liệu được OCR và đưa vào knowledge graph ngay trong máy. Mặc định là dữ
  liệu mức A, chờ duyệt, không được dùng làm căn cứ khi trả lời chat." Links back to `/` and `/graph`.
- A drop zone + `<input type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.docx,.txt,.md">`.
  Files upload one after another; each shows "Đang xử lý…" then its result or the error `detail`.
- Table of all uploads (from GET, refreshed after every action), newest first: file name, status badge (chờ duyệt / đã
  duyệt / đã loại / lỗi), pages, OCR pages, OCR confidence in %, parse mode (Điều/Khoản or Đoạn), nodes, references.
  Row actions: "Xem trên graph" (`/graph?doc_id=<doc_id>`), "Duyệt", "Loại", "Xoá" (confirm()). A row click toggles the
  `preview` text (pre-wrap, max-height with scroll).
- No polling loops; no localStorage needed.

## Graph page
On mount read `doc_id` from `window.location.search`. When present, fetch
`/api/graph?doc_id=<id>&uploads=1&top_k=150&mode=law` instead of the query URL, and show a banner above the graph:
"Đang xem tài liệu tải lên: <document label> — <status>" with a link "Bỏ lọc" back to `/graph`. Keep everything else
unchanged (a plain `/graph` must behave exactly as before).

## Chat header
Add a link to `/upload` (title "Tải tài liệu lên") next to the existing graph link, same class.

## Done when
```
docker compose exec -T web npx tsc --noEmit
docker compose exec -T web npx next lint --dir app --dir components   # no new errors
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/upload    # 200
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
