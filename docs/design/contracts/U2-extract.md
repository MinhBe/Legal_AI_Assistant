# Contract U2 — text extraction + offline OCR for uploaded files

Plan: `docs/design/upload-ocr-kg-plan.md` (step U2). Read `AGENTS.md` first. Do not commit; the Tech Lead reviews and commits.

## Files you may create or edit (nothing else)
- `backend/app/upload/__init__.py` (empty)
- `backend/app/upload/extract.py`
- `backend/tests/test_upload_extract.py`

## API (exact names)
```python
MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 50
MIN_TEXT_CHARS = 30          # a PDF page with fewer non-space chars is treated as scanned -> OCR

class UnsupportedFile(ValueError): ...
class TooLarge(ValueError): ...

@dataclass
class PageText:
    page: int                 # 1-based
    text: str
    method: str               # "text" (PDF text layer) | "ocr" | "docx" | "plain"
    conf: float | None = None # mean word confidence 0..1, OCR pages only

@dataclass
class Extraction:
    filename: str
    mime: str                 # "application/pdf", "image/png", "image/jpeg", "image/tiff", ...,
                              # "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"
    pages: list[PageText]
    @property
    def text(self) -> str: ...        # "\n\n".join of non-empty page texts
    @property
    def ocr_pages(self) -> int: ...   # number of pages with method == "ocr"
    @property
    def mean_conf(self) -> float | None: ...  # mean conf over OCR pages, None if no OCR page

def ocr_image(img) -> tuple[str, float | None]: ...   # img is a PIL.Image.Image
def extract(data: bytes, filename: str) -> Extraction: ...
```

## Behaviour
- Type by lower-case extension, confirmed by magic bytes for PDF (`%PDF`), PNG and JPEG. Supported: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp`, `.docx`, `.txt`, `.md`. Anything else, or a corrupt file → `UnsupportedFile`.
- `len(data) > MAX_BYTES` or more than `MAX_PAGES` pages/frames → `TooLarge`.
- PDF: `pypdfium2`. Per page: `page.get_textpage().get_text_range()`. If it has fewer than `MIN_TEXT_CHARS` non-space chars, render with `page.render(scale=300/72).to_pil()` and OCR it (method `"ocr"`); otherwise method `"text"`.
- Images: Pillow; every frame of a multi-frame TIFF is a page (`ImageSequence`); each frame is OCRed.
- DOCX: `python-docx`; paragraphs in body order, then each table row as `cell | cell`; one page, method `"docx"`.
- TXT/MD: decode `utf-8-sig`, fall back to `cp1258`, then `latin-1`; one page, method `"plain"`.
- All text: `unicodedata.normalize("NFC")`, `\r\n` → `\n`, strip trailing spaces per line.
- OCR (`ocr_image`): convert to `"L"`; if width < 1500 px upscale 2x (LANCZOS); write a temp PNG; run
  `["tesseract", <png>, "stdout", "-l", "vie+eng", "--psm", "3", "tsv"]` with `subprocess.run(..., timeout=120)`.
  Parse the TSV: keep rows with `level == 5` and non-empty text; group words by (block_num, par_num, line_num) joined with
  one space; lines joined with `\n`; a new paragraph (block or par change) adds an empty line. `conf` = mean of word confs
  that are >= 0, divided by 100. Delete the temp file. Tesseract missing or failing → raise `RuntimeError` with a short message.
- No network calls, no LLM calls, no new dependencies (pypdfium2, pillow, python-docx and tesseract vie are installed).

## Tests (`backend/tests/test_upload_extract.py`)
Samples are in the repo at `data/samples/upload/` (inside the container: `/app/data/samples/upload/`). Locate them with
`Path(__file__).resolve().parents[1] / "data" / "samples" / "upload"`; skip a test when its file is missing. Skip OCR tests
when `shutil.which("tesseract")` is None.
1. `hoi-dap-noi-bo.txt` → 1 page, method `plain`, text contains `Điều 35`.
2. `hop-dong-lao-dong-mau.docx` → method `docx`, text contains `Điều 36` and `Trần Thị Mẫu` (table cell).
3. `noi-quy-lao-dong.pdf` → every page method `text`, `ocr_pages == 0`, text contains `Điều 125` and `KỶ LUẬT LAO ĐỘNG`.
4. `quyet-dinh-ky-luat-scan.jpg` → 1 page, method `ocr`, `mean_conf > 0.6`, text (case-insensitive) contains `bộ luật lao động`,
   `điều 125` and `kỷ luật`.
5. `quyet-dinh-ky-luat-scan.pdf` → `ocr_pages == 1`, text contains `Điều 125`.
6. `extract(b"MZ\x90\x00", "x.exe")` → `UnsupportedFile`; `extract(b"%PDF-broken", "x.pdf")` → `UnsupportedFile`.
7. `TooLarge`: monkeypatch `extract.MAX_BYTES` to 10 and pass 11 bytes of a `.txt`.

## Done when (run from the repo root)
```
docker compose exec -T api python -m pytest -q tests/test_upload_extract.py
docker compose exec -T api python -m pytest -q -m "not llm"        # baseline: 165 passed, must stay green
docker compose exec -T api ruff check app/upload tests/test_upload_extract.py
```
If OCR text misses a diacritic in test 4, relax that assertion only by testing words OCR gets right in the sample; do not
weaken tests 1–3, 5–7. Max 2 fix attempts per failure; then stop and report the failing output. Finish with a 5-line summary.
