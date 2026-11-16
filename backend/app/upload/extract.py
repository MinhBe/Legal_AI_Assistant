"""Trích xuất văn bản từ tệp tải lên (upload-ocr-kg-plan, U2).

PDF lấy lớp văn bản bằng pypdfium2; trang nào ít chữ (bản scan) thì render rồi OCR
bằng tesseract vie+eng. Ảnh OCR từng khung. DOCX/TXT/MD đọc thẳng, không OCR.
Không gọi mạng, không gọi LLM.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageSequence

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 50
MIN_TEXT_CHARS = 30  # trang PDF ít hơn ngần này ký tự không trắng -> coi là bản scan

PDF_MIME = "application/pdf"
DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
IMAGE_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}
TEXT_MIMES = {".txt": "text/plain", ".md": "text/markdown"}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


class UnsupportedFile(ValueError):
    """Định dạng không hỗ trợ, hoặc tệp hỏng."""


class TooLarge(ValueError):
    """Tệp quá lớn hoặc quá nhiều trang."""


@dataclass
class PageText:
    page: int  # 1-based
    text: str
    method: str  # "text" | "ocr" | "docx" | "plain"
    conf: float | None = None  # độ tin cậy trung bình 0..1, chỉ trang OCR


@dataclass
class Extraction:
    filename: str
    mime: str
    pages: list[PageText]

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)

    @property
    def ocr_pages(self) -> int:
        return sum(1 for p in self.pages if p.method == "ocr")

    @property
    def mean_conf(self) -> float | None:
        confs = [p.conf for p in self.pages if p.method == "ocr" and p.conf is not None]
        return sum(confs) / len(confs) if confs else None


def extract(data: bytes, filename: str) -> Extraction:
    """Đọc tệp -> danh sách trang kèm phương pháp lấy chữ."""
    if len(data) > MAX_BYTES:
        raise TooLarge(f"tệp lớn hơn {MAX_BYTES} byte")
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            _check_magic(data, b"%PDF", suffix)
            mime, pages = PDF_MIME, _pdf_pages(data)
        elif suffix in IMAGE_MIMES:
            magic = {"image/png": PNG_MAGIC, "image/jpeg": JPEG_MAGIC}.get(
                IMAGE_MIMES[suffix]
            )
            if magic:
                _check_magic(data, magic, suffix)
            mime, pages = IMAGE_MIMES[suffix], _image_pages(data)
        elif suffix == ".docx":
            mime, pages = DOCX_MIME, _docx_pages(data)
        elif suffix in TEXT_MIMES:
            mime, pages = TEXT_MIMES[suffix], _plain_pages(data)
        else:
            raise UnsupportedFile(f"không hỗ trợ định dạng {suffix or filename!r}")
    except (UnsupportedFile, TooLarge):
        raise
    except pdfium.PdfiumError as exc:  # PDF hỏng; lớp này là RuntimeError con
        raise UnsupportedFile(f"không đọc được {filename}: {exc}") from exc
    except RuntimeError:  # lỗi OCR: thiếu tesseract / tesseract hỏng
        raise
    except Exception as exc:  # tệp hỏng: thư viện đọc ném đủ loại lỗi
        raise UnsupportedFile(f"không đọc được {filename}: {exc}") from exc
    return Extraction(filename=filename, mime=mime, pages=pages)


def ocr_image(img: Image.Image) -> tuple[str, float | None]:
    """OCR một ảnh PIL bằng tesseract; trả (chữ, conf 0..1)."""
    gray = img.convert("L")
    if gray.width < 1500:  # ảnh nhỏ thì phóng to, tesseract đọc chính xác hơn
        gray = gray.resize((gray.width * 2, gray.height * 2), Image.LANCZOS)
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "page.png"
        gray.save(png, format="PNG")
        try:
            proc = subprocess.run(
                ["tesseract", str(png), "stdout", "-l", "vie+eng", "--psm", "3", "tsv"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,  # mã lỗi được xử lý ngay bên dưới
            )
        except FileNotFoundError as exc:
            raise RuntimeError("không tìm thấy tesseract") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("tesseract chạy quá 120 giây") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract lỗi: {proc.stderr.strip()[:200]}")
    return _parse_tsv(proc.stdout)


def _parse_tsv(tsv: str) -> tuple[str, float | None]:
    """TSV của tesseract -> chữ có xuống dòng/đoạn + conf trung bình."""
    lines: list[str] = []
    words: list[str] = []
    confs: list[float] = []
    line_key = par_key = None
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        word = cols[11].strip()
        if not word:
            continue
        par, key = (cols[2], cols[3]), (cols[2], cols[3], cols[4])
        if line_key is not None and key != line_key:
            lines.append(" ".join(words))
            words = []
            if par != par_key:  # sang đoạn mới -> cách một dòng trống
                lines.append("")
        line_key, par_key = key, par
        words.append(word)
        conf = float(cols[10])
        if conf >= 0:
            confs.append(conf)
    if words:
        lines.append(" ".join(words))
    text = _normalize("\n".join(lines))
    conf = round(sum(confs) / len(confs) / 100, 4) if confs else None
    return text, conf


def _pdf_pages(data: bytes) -> list[PageText]:
    doc = pdfium.PdfDocument(data)
    try:
        if len(doc) > MAX_PAGES:
            raise TooLarge(f"tệp có hơn {MAX_PAGES} trang")
        pages = []
        for i in range(len(doc)):
            page = doc[i]
            text = _normalize(page.get_textpage().get_text_range())
            if _char_count(text) < MIN_TEXT_CHARS:
                text, conf = ocr_image(page.render(scale=300 / 72).to_pil())
                pages.append(PageText(i + 1, text, "ocr", conf))
            else:
                pages.append(PageText(i + 1, text, "text"))
    finally:
        doc.close()
    return pages


def _image_pages(data: bytes) -> list[PageText]:
    with Image.open(io.BytesIO(data)) as im:
        frames = [frame.copy() for frame in ImageSequence.Iterator(im)]
    if len(frames) > MAX_PAGES:
        raise TooLarge(f"ảnh có hơn {MAX_PAGES} khung")
    pages = []
    for i, frame in enumerate(frames):
        text, conf = ocr_image(frame)
        pages.append(PageText(i + 1, text, "ocr", conf))
    return pages


def _docx_pages(data: bytes) -> list[PageText]:
    import docx  # python-docx; chỉ cần khi gặp .docx

    document = docx.Document(io.BytesIO(data))
    blocks = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            blocks.append(" | ".join(cell.text for cell in row.cells))
    return [PageText(1, _normalize("\n".join(blocks)), "docx")]


def _plain_pages(data: bytes) -> list[PageText]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1258")
        except UnicodeDecodeError:
            text = data.decode("latin-1")  # luôn giải mã được
    return [PageText(1, _normalize(text), "plain")]


def _check_magic(data: bytes, magic: bytes, suffix: str) -> None:
    if not data.startswith(magic):
        raise UnsupportedFile(f"nội dung tệp không khớp định dạng {suffix}")


def _char_count(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()
