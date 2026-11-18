"""Mở rộng kho ngoài lao động từ Công báo (Minh chọn "Mở rộng kho văn bản", 18/11/2026).

  python -m scripts.fetch_corpus_ext --probe        # đọc trang: hiệu lực, tệp tải
  python -m scripts.fetch_corpus_ext --ingest       # tải + nạp, trạng thái pending_review

Chỉ trang và tệp công khai của congbao.chinhphu.vn (robots.txt, giãn cách ≥ 5 s của
Fetcher, không cookie/đăng nhập). Văn bản nạp vào ở trạng thái chờ duyệt: Minh duyệt ở
/upload như NĐ 399; script này KHÔNG duyệt gì. Lĩnh vực + mốc hiệu lực ghi vào doc_meta.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from loguru import logger

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import DocMeta, LegalDocument
from app.intel import fetch, official
from app.intel.scheduler import _fetcher
from app.upload import extract as upload_extract
from app.upload import service as upload_service

# Giới hạn 50 trang của /upload là để chặn tệp người dùng tốn OCR. Văn bản Công báo là
# nguồn chính thức, dài vài trăm trang (BLHS, BLDS, NĐ 102/2024): nâng trần cho riêng script này.
upload_extract.MAX_PAGES = 1200

CB = "https://congbao.chinhphu.vn/van-ban/"
# (domain, số hiệu gốc, tiêu đề, trang Công báo, văn bản được hợp nhất / ghi chú, thay thế)
CANDIDATES: list[dict] = [
    {"domain": "dat_dai", "number": "31/2024/QH15", "title": "Luật Đất đai 2024 (VBHN 44/VBHN-VPQH)",
     "url": CB + "van-ban-hop-nhat-so-44vbhnvpqh-469129.htm", "file_key": "44/VBHN-VPQH", "orig_url": CB + "nghi-quyet-so-312024qh15-41329.htm",
     "consolidates": "Luật 31/2024/QH15 + các luật sửa đổi"},
    {"domain": "dat_dai", "number": "101/2024/NĐ-CP",
     "title": "Nghị định 101/2024/NĐ-CP đăng ký, cấp Giấy chứng nhận",
     "url": CB + "nghi-dinh-so-1012024ndcp-42434.htm", "file_key": "101-2024-NĐ-CP"},
    {"domain": "dat_dai", "number": "102/2024/NĐ-CP",
     "title": "Nghị định 102/2024/NĐ-CP quy định chi tiết Luật Đất đai",
     "url": CB + "nghi-dinh-so-1022024ndcp-42485.htm", "file_key": "102-2024-NĐ-CP"},
    {"domain": "hinh_su", "number": "100/2015/QH13", "title": "Bộ luật Hình sự (VBHN 135/VBHN-VPQH)",
     "url": CB + "van-ban-hop-nhat-so-135vbhnvpqh-46165.htm", "file_key": "135-VBHN-VPQH", "effective_override": "2018-01-01",
     "effective_note": "lùi hiệu lực theo NQ 144/2016/QH13 và NQ 41/2017/QH14", "orig_url": CB + "luat-so-1002015qh13-18442.htm",
     "consolidates": "Bộ luật 100/2015/QH13 + Luật 12/2017/QH14 + sửa đổi 2025"},
    {"domain": "xu_phat_hc", "number": "282/2025/NĐ-CP",
     "title": "Nghị định 282/2025/NĐ-CP xử phạt VPHC an ninh, trật tự, an toàn xã hội",
     "url": CB + "nghi-dinh-so-2822025ndcp-46543.htm", "file_key": "282-2025-NĐ-CP", "replaces": "144/2021/NĐ-CP"},
    {"domain": "hon_nhan_gia_dinh", "number": "52/2014/QH13",
     "title": "Luật Hôn nhân và gia đình (VBHN 121/VBHN-VPQH)",
     "url": CB + "van-ban-hop-nhat-so-121vbhnvpqh-46059.htm", "file_key": "121-VBHN-VPQH", "orig_url": CB + "luat-so-522014qh13-6127.htm",
     "consolidates": "Luật 52/2014/QH13 + các luật sửa đổi"},
    {"domain": "thue_tncn", "number": "109/2025/QH15", "title": "Luật Thuế thu nhập cá nhân 2025",
     "url": CB + "luat-so-1092025qh15-468671.htm", "file_key": "109/2025/QH15"},
    {"domain": "dan_su", "number": "91/2015/QH13", "title": "Bộ luật Dân sự 2015",
     "url": CB + "luat-so-912015qh13-18397.htm", "file_key": "91_2015_QH13"},
]
OUT = Path("data/corpus_ext")


def probe(render) -> list[dict]:
    found = []
    for c in CANDIDATES:
        html = render(c["url"])
        # trang còn liệt kê tệp của văn bản khác ở cột bên: chỉ giữ tệp mang khoá của văn bản này
        files = [f for f in official.parse_files(html, c["url"]) if c["file_key"] in f["name"]]
        eff = official.effective_date(html)
        if c.get("orig_url"):  # VBHN: ngày trên trang là ngày hợp nhất, lấy hiệu lực của văn bản gốc
            eff = official.effective_date(render(c["orig_url"]))
        if eff is not None and eff.year < 1950:  # trang để "01/01/1900" = không có ngày
            eff = None
        row = {**c, "effective_from": eff.isoformat() if eff else None,
               "files": [f["name"] for f in files], "file_urls": [f["url"] for f in files],
               "exts": [f["ext"] for f in files], "page_ok": bool(html)}
        found.append(row)
        print(json.dumps({k: row[k] for k in ("number", "title", "effective_from", "files")},
                         ensure_ascii=False), flush=True)
    return found


def _merge_pdfs(parts: list[bytes]) -> bytes:
    """Công báo cũ chia một văn bản thành nhiều tệp PDF theo số trang: ghép lại theo thứ tự."""
    import io

    import pypdfium2 as pdfium

    out = pdfium.PdfDocument.new()
    for data in parts:
        src = pdfium.PdfDocument(data)
        out.import_pages(src)
    buf = io.BytesIO()
    out.save(buf)
    return buf.getvalue()


def _documents(row: dict, fetcher, settings):
    """Các cách lấy văn bản theo thứ tự ưu tiên: một DOCX; hoặc mọi phần PDF ghép lại.
    Sinh (tên tệp, bytes | None, lỗi)."""
    limit = settings.intel_fulltext_max_mb * 1024 * 1024
    entries = list(zip(row["files"], row["file_urls"], row["exts"], strict=True))
    for name, url, ext in entries:
        if ext == "docx":
            code, data, _ = fetcher.get_bytes(url, max_bytes=limit)
            yield (Path(name).name.replace("/", "-"), data, "") if code == 200 and data \
                else (name, None, f"HTTP {code} ({name})")
            return
    pdfs = sorted({n: u for n, u, e in entries if e == "pdf"}.items())  # tên chứa số trang
    parts = []
    for name, url in pdfs:
        code, data, _ = fetcher.get_bytes(url, max_bytes=limit)
        if code != 200 or not data:
            yield name, None, f"HTTP {code} ({name})"
            return
        parts.append(data)
    if parts:
        stem = row["number"].replace("/", "-")
        yield f"{stem}.pdf", parts[0] if len(parts) == 1 else _merge_pdfs(parts), ""


def ingest(found: list[dict], fetcher, settings) -> list[dict]:
    db = SessionLocal()
    report = []
    try:
        for row in found:
            status, upload_id, error = "not_found", None, ""
            for name, data, err in _documents(row, fetcher, settings):
                if data is None:
                    status, error = "failed", err
                    continue
                up = upload_service.save_upload(db, data, name, title=row["title"])
                if up.status == "failed" or not up.doc_id:
                    status, error = "failed", f"nạp lỗi: {up.error}"
                    continue
                status, upload_id = up.status, up.upload_id
                meta = db.get(DocMeta, up.doc_id) or DocMeta(doc_id=up.doc_id)
                meta.domain = row["domain"]
                meta.number = row["number"]
                eff = row.get("effective_override") or row["effective_from"]
                meta.effective_from = date.fromisoformat(eff) if eff else None
                meta.consolidates = "; ".join(
                    x for x in (row.get("consolidates"), row.get("effective_note")) if x) or None
                meta.source_url = row["url"]
                db.merge(meta)
                if row.get("replaces"):  # văn bản cũ trong kho (nếu có) hết hiệu lực khi văn bản này có hiệu lực
                    old = db.query(DocMeta).filter(DocMeta.number == row["replaces"]).first()
                    if old is not None:
                        old.replaced_by, old.effective_to = row["number"], meta.effective_from
                doc = db.get(LegalDocument, up.doc_id)
                if doc is not None:
                    doc.number = doc.number or row["number"]
                    doc.effective_date = doc.effective_date or meta.effective_from
                    doc.source_url = row["url"]
                db.commit()
                break
            report.append({"number": row["number"], "title": row["title"], "status": status,
                           "upload_id": upload_id, "error": error,
                           "effective_from": row["effective_from"], "url": row["url"]})
            logger.info("{} -> {} {}", row["title"], status, error)
    finally:
        db.close()
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--ingest", action="store_true")
    args = p.parse_args()
    settings = get_settings()
    fetcher = _fetcher(settings)
    OUT.mkdir(parents=True, exist_ok=True)
    with fetch.Renderer(fetcher) as renderer:
        found = probe(renderer.render)
    (OUT / "probe.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.ingest:
        report = ingest(found, fetcher, settings)
        (OUT / "ingest.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
