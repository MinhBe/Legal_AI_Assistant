"""Lấy thử bản án công bố từ congbobanan.toaan.gov.vn (docs/design/case-sources.md).

    python -m scripts.fetch_cases --limit 200 --types "Lao động,Dân sự,Hôn nhân và gia đình"

- Trang không có robots.txt (404), nên không có đường dẫn bị cấm. Vẫn giãn cách ≥ 5 s giữa mọi
  yêu cầu và ghi rõ User-Agent.
- Lấy ID mới nhất từ trang chủ, rồi lùi dần theo ID. Đọc trang chi tiết, lọc theo Loại án, tải PDF
  toàn văn và chỉ lấy lớp chữ: bản scan bị bỏ qua, không OCR (máy nhà không chạy việc nặng).
- Chạy ở máy chủ Windows (`python -X utf8 -m scripts.fetch_cases` trong backend/): container
  Linux thiếu chứng chỉ trung gian của trang; không bao giờ tắt kiểm TLS.
- Đầu ra: data/raw/cases/congbobanan/<id>.json. Chạy lại thì bỏ qua ID đã làm (kể cả ID đã loại,
  ghi ở _seen.txt).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from pathlib import Path

import httpx

BASE = "https://congbobanan.toaan.gov.vn"
UA = "LawVN-research-bot/0.1 (nghien cuu phap ly; gian cach 5s)"
OUT = Path(__file__).resolve().parents[2] / "data/raw/cases/congbobanan"
PACE = 5.0
_last = 0.0


def _verify():
    """Trang toà án thiếu chứng chỉ trung gian trong chuỗi: dùng kho chứng chỉ của hệ điều hành
    (truststore, Windows tự lấy chứng chỉ trung gian). Vẫn kiểm chứng chỉ, không tắt TLS."""
    try:
        import ssl

        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


def get(client: httpx.Client, url: str) -> httpx.Response:
    global _last
    wait = _last + PACE - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    for attempt in range(3):  # trang toà án hay chậm: đợi lâu dần rồi thử lại, không dừng cả lượt
        try:
            return client.get(url, timeout=60, follow_redirects=True)
        except httpx.TransportError:
            if attempt == 2:
                return httpx.Response(599, request=httpx.Request("GET", url))
            time.sleep(30 * (attempt + 1))
            _last = time.monotonic()


def text_of(page: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


_FIELDS = ["Tên bản án", "Quan hệ pháp luật", "Cấp xét xử", "Loại vụ/việc", "Loại án",
           "Tòa án xét xử", "Áp dụng án lệ", "Đính chính", "Thông tin về vụ/việc",
           "Thông tin về vụ án", "Tổng số lượt"]


def meta_of(page: str) -> dict:
    t = text_of(page)
    out = {}
    for i, k in enumerate(_FIELDS):
        m = re.search(re.escape(k) + r"\s*:\s*(.*?)(?=\s(?:" + "|".join(map(re.escape, _FIELDS[i + 1:] or ["$^"])) + r")\s*:|$)", t)
        if m:
            out[k] = m.group(1).strip()[:2000]
    return out


def pdf_text(data: bytes) -> str:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    try:
        return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    finally:
        doc.close()


def latest_id(client: httpx.Client) -> int:
    ids = [int(x) for x in re.findall(r"/2ta(\d+)t1cvn/chi-tiet-ban-an", get(client, BASE + "/").text)]
    if not ids:
        raise SystemExit("không thấy bản án nào trên trang chủ")
    return max(ids)


def run(limit: int, types: list[str], max_requests: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seen_path = OUT / "_seen.txt"
    seen = set(seen_path.read_text().split()) if seen_path.exists() else set()
    kept = len(list(OUT.glob("*.json")))
    reqs = 0
    with httpx.Client(headers={"User-Agent": UA}, verify=_verify()) as client, seen_path.open("a") as seen_f:
        cur = latest_id(client)
        reqs += 1
        while kept < limit and reqs < max_requests:
            cid, cur = str(cur), cur - 1
            if cid in seen:
                continue
            seen_f.write(cid + "\n")
            seen_f.flush()
            r = get(client, f"{BASE}/2ta{cid}t1cvn/chi-tiet-ban-an")
            reqs += 1
            if r.status_code != 200 or "Tên bản án" not in r.text:
                continue
            meta = meta_of(r.text)
            kind = meta.get("Loại vụ/việc") or meta.get("Loại án") or ""
            meta["loai"] = kind
            if types and not any(t.lower() in kind.lower() for t in types):
                continue
            pdf = re.search(r'href="(/5ta' + cid + r't1cvn/[^"]+\.pdf)"', r.text)
            if not pdf:
                continue
            p = get(client, BASE + httpx.URL(pdf.group(1)).raw_path.decode())
            reqs += 1
            if p.status_code != 200 or not p.content.startswith(b"%PDF"):
                continue
            try:
                body = pdf_text(p.content)
            except Exception:  # noqa: BLE001 — PDF hỏng: bỏ
                continue
            if len(body) < 1500:  # bản scan, không có lớp chữ
                continue
            (OUT / f"{cid}.json").write_text(json.dumps(
                {"id": cid, "source": "congbobanan", "url": f"{BASE}/2ta{cid}t1cvn/chi-tiet-ban-an",
                 "meta": meta, "text": body, "fetched": time.strftime("%Y-%m-%dT%H:%M:%S")},
                ensure_ascii=False, indent=1), encoding="utf-8")
            kept += 1
            print(kept, cid, meta.get("loai"), meta.get("Tên bản án", "")[:80], flush=True)
    print("xong:", kept, "bản án,", reqs, "yêu cầu")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--types", default="Lao động,Dân sự,Hôn nhân và gia đình,Hành chính")
    ap.add_argument("--max-requests", type=int, default=3000)
    a = ap.parse_args()
    run(a.limit, [t.strip() for t in a.types.split(",") if t.strip()], a.max_requests)


if __name__ == "__main__":
    main()
