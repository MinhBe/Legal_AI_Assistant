# lawvn-ingest: hợp đồng nhập dữ liệu (19/11/2026)

## Tóm tắt (tiếng Việt)

`packages/lawvn-ingest` là gói dùng chung cho Legal Agentic và Pi. Mỗi **nguồn** là một *adapter*,
gồm hai việc: liệt kê mục (`list_items`) và tải một mục (`fetch`). Gói lo phần còn lại:
- ghi tệp vào `record/inbox`, kèm tệp mô tả `<tệp>.meta.json`;
- ghi thêm một dòng vào `manifest.jsonl`;
- không tải trùng (theo cặp nguồn, id);
- lọc theo `--since`;
- đẩy lên Kaggle để chép lời rồi che PII.

Có sẵn 3 adapter:
- `folder`: tệp anh tự đặt vào một thư mục;
- `fb-dyi`: bản xuất "Tải thông tin của bạn" của Facebook;
- `fb-graph`: Graph API trên chính tài khoản của anh.

Minh tự viết adapter cho nguồn của mình trong một package riêng và khai báo entry point. Không
phải sửa code của gói này.

**Bắt buộc:** mọi mục có `consent` thuộc `own`, `licensed` hoặc `public-official`. Bộ lưu
từ chối mọi giá trị khác. Claude chỉ chạy adapter lấy dữ liệu theo đúng điều khoản của nguồn,
không chạy adapter cào trái điều khoản hay vượt đăng nhập.

Cài đặt (máy nhà, nhẹ, không phụ thuộc thêm):

    pip install -e packages/lawvn-ingest            # thêm [graph] nếu dùng fb-graph
    lawvn-ingest adapters

## Contract (English)

### Item

```python
@dataclass(frozen=True)
class Item:
    id: str                  # stable within the source; dedupe key is (source, id)
    source: str              # e.g. "facebook-dyi"
    consent: str             # "own" | "licensed" | "public-official"  (enforced)
    url: str = ""            # whatever fetch() needs to locate the media
    posted_at: str | None    # ISO 8601; used by --since
    caption: str = ""
    media_type: str = "video"  # video | audio | text
    title: str = ""
    extra: dict = {}
```

### Adapter

```python
class Adapter(Protocol):
    name: str
    def list_items(self, since: str | None = None) -> Iterable[Item]: ...
    def fetch(self, item: Item, out_dir: Path) -> Path: ...   # write media into out_dir, return path
```

Constructor keyword arguments are the adapter's options (`--opt key=value` on the CLI, all strings).
Name files with `lawvn_ingest.stem_for(item)` so stems are unique and safe.

### Registration

Built-ins load without installation. A third-party package adds itself in its own pyproject:

```toml
[project.entry-points."lawvn_ingest.adapters"]
my-source = "my_pkg.adapter:MyAdapter"
```

### Output (per fetched item, in the output dir, default `record/inbox`)

- `<stem><ext>`: the media;
- `<stem><ext>.meta.json`: the Item plus `file`;
- one JSON line appended to `manifest.jsonl` (append-only).

The `.meta.json` and manifest hold **unmasked** captions: local only, never sent to an external model.

### Consumers

- **CLI:** `lawvn-ingest adapters | list | fetch [--dry-run] | push [--collect]`, JSON on stdout.
- **Legal Agentic:** `lawvn_ingest.pipeline.enqueue("fb-dyi", path=..., push=True)`. `push` runs
  `tools/record_inbox.py`: Kaggle dataset version → ASR kernel → PII kernel. `--collect`
  downloads only `*.masked.json`. Then prompt v2.1 runs on the masked text.
- **Pi:** `packages/lawvn-ingest/pi/SKILL.md` calls the CLI. Installing it into a Pi profile is
  Minh's step. No MCP wrapper yet: FastMCP is not installed.

### Example third-party adapter (stub)

```python
# my_pkg/adapter.py
from pathlib import Path
from lawvn_ingest import Item, stem_for

class MyAdapter:
    name = "my-source"

    def __init__(self, path: str, consent: str = "licensed") -> None:
        self.path, self.consent = Path(path), consent

    def list_items(self, since=None):
        for p in sorted(self.path.glob("*.mp4")):
            yield Item(id=p.stem, source="my-source", consent=self.consent, url=str(p))

    def fetch(self, item, out_dir):
        dst = Path(out_dir) / f"{stem_for(item)}.mp4"
        dst.write_bytes(Path(item.url).read_bytes())
        return dst
```

### fb-graph one-time setup (Minh)

1. developers.facebook.com: create an app and keep it in Development mode. The admin can grant
   themselves `user_videos` without App Review.
2. Graph API Explorer: Get User Access Token with `user_videos`. Optionally extend it to about
   60 days in the Access Token Debugger.
3. Put the token on one line in `keys/facebook_user_token.txt`. That path is gitignored.
