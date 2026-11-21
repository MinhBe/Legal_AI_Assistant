# webgather

Một package thu thập web **nhẹ, độc lập**, đặt sự tuân thủ lên trước. Dùng được
như một tool cho agent (Claude, Codex, pi.dev) hoặc như thư viện Python. Lõi chỉ
dùng thư viện chuẩn, không cần cài gì thêm.

Package này **không phụ thuộc** vào LawVN hay bất kỳ sản phẩm nào. Sản phẩm tự
cắm bộ che PII và bộ chính sách nguồn của mình vào.

## Nguyên tắc

Cổng tuân thủ **từ chối, không lách**. Trong package không có nhánh nào thử lại
một URL bị chặn bằng user-agent giả, proxy, cookie hay giải CAPTCHA — những thứ
đó đơn giản là không tồn tại ở đây.

Luồng luôn cố định:

```
Nguồn  ->  Cổng tuân thủ  ->  Lấy về  ->  Khử danh tính  ->  Record
```

Cổng quyết định **trước khi** gửi request, và chặn: robots.txt không cho, URL
riêng tư (nhóm, trang cá nhân, tin nhắn), chính sách từng trang, hoặc chưa đủ
giãn cách. Sau khi lấy về, cổng còn soi phản hồi để bắt tường đăng nhập và
CAPTCHA mà bước trước chưa thấy. Văn bản trả về đã được khử danh tính.

## Dùng nhanh

```python
from webgather import collect

r = collect("https://trang-cong-khai.gov.vn/hoi-dap/123")
if r.ok:
    print(r.title, r.text)      # đã khử danh tính
else:
    print("bị chặn:", r.decision.reason, r.decision.detail)
```

CLI (in JSON ra stdout, hợp cho agent shell / pi.dev):

```bash
webgather check   https://example.gov.vn/faq/1   # chỉ xem quyết định, không lấy
webgather collect https://example.gov.vn/faq/1   # lấy về + khử danh tính
```

Mã thoát: `0` cho phép/ok, `2` bị cổng chặn, `1` lỗi dùng sai.

## Như một tool của agent

```python
from webgather.tool import TOOL_SCHEMA, run_tool

# TOOL_SCHEMA là JSON schema để đăng ký tool với model.
out = run_tool({"action": "collect", "url": "https://x.gov.vn/faq/1"})
# -> {"ok": true, "decision": {...}, "title": "...", "text": "...", "url_hash": "..."}
```

`action` là `"check"` (không lấy, chỉ trả quyết định) hoặc `"collect"`.

## Chính sách từng nguồn

```python
from webgather import ComplianceGate, Policy, SourcePolicy
from webgather.pipeline import collect

policy = Policy([
    SourcePolicy(
        host="hoidap.example.vn",
        legal_basis="robots.txt cho phép; trang hỏi đáp công khai, đã ẩn danh",
        min_delay=5.0,
        allow_paths=[r"^/hoi-dap/"],
    ),
])
gate = ComplianceGate(policy=policy)
r = collect("https://hoidap.example.vn/hoi-dap/5", gate=gate)
```

Host không có chính sách sẽ theo mặc định thận trọng (tôn trọng robots, giãn
cách 5 giây, chặn URL riêng tư). Đặt `Policy(allow_unknown_hosts=False)` để chỉ
cho phép host đã khai báo.

## Thay bộ che PII của bạn

Bộ mặc định `VietnamesePiiMasker` che số điện thoại, CCCD/CMND, email, và tên
người / công ty theo từ khoá gợi ý, với bí danh nhất quán (Nguyễn Văn B, Công ty
X, `[SĐT-1]`). Sản phẩm có bộ mạnh hơn (ví dụ cổng G1 của LawVN) chỉ cần truyền
vào — hợp đồng là protocol `Masker.mask(text) -> text`:

```python
from webgather.pipeline import collect

class G1Masker:
    def mask(self, text: str) -> str: ...

collect(url, masker=G1Masker())
```

## Thêm nguồn mới

Một nguồn = một class khai báo `name`, `auth` (chỉ `none`, `api_key` hoặc
`user_upload` — không có cookie/session/mật khẩu) và `plan()` sinh ra các URL.
Package khác tự đăng ký trong `pyproject.toml` của nó, không sửa file ở đây:

```toml
[project.entry-points."webgather.sources"]
my-source = "my_pkg.adapter:MySource"
```

## Giới hạn, cố ý

- Không đăng nhập, không mượn cookie/token, không giải CAPTCHA, không né chặn.
- Không nhóm kín, trang cá nhân riêng tư, tin nhắn.
- Lõi chỉ lấy HTML tĩnh. Trang động cần trình duyệt thật (tuỳ chọn `browser`),
  nằm ngoài lõi.
- Bộ che PII là lớp nhẹ, không phải bảo đảm; sản phẩm nên phủ thêm lớp của mình.

## Căn cứ pháp lý (Việt Nam, 11/2026)

- Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 và Nghị định 356/2025/NĐ-CP (thay thế
  Nghị định 13/2023), hiệu lực 01/01/2026: khử danh tính tại cửa vào để tránh
  xử lý dữ liệu cá nhân không có căn cứ.
- Bộ luật Hình sự Điều 289: không vượt tường đăng nhập, mã truy cập.
