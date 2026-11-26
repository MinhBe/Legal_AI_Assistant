# Nguồn tình huống thật: bản án công bố, hỏi đáp pháp luật (kiểm ngày 20/11/2026)

Minh 20/11/2026 đồng ý thêm tình huống thật từ bản án công bố và hỏi đáp pháp luật trên cổng chính
phủ. Quy tắc:
- chỉ đường dẫn robots.txt cho phép;
- giãn cách ≥ 5 s, User-Agent ghi rõ "LegalAgentic-research-bot";
- không vượt CAPTCHA, cookie thử JS hay đăng nhập;
- lấy thử tối đa 200 mục mỗi nguồn;
- vẫn chạy bộ che PII (bản án đã ẩn danh một phần, ví dụ "Tô Đình L");
- văn bản là dữ liệu công khai, nhưng tình huống sinh ra vẫn chờ luật sư duyệt.

## Kết quả kiểm robots.txt và truy cập

| Nguồn | robots.txt | Truy cập | Kết luận |
|---|---|---|---|
| congbobanan.toaan.gov.vn (Cổng công bố bản án, án lệ) | không có (404), không cấm | trang chi tiết `/2ta<ID>t1cvn/chi-tiet-ban-an` đọc được; toàn văn là PDF ở `/5ta<ID>t1cvn/…pdf`; danh sách tải bằng postback ASP.NET | **dùng**: đi theo liên kết trang chủ và lùi theo ID, lọc Loại án |
| baohiemxahoi.gov.vn/hoidap (Hỏi đáp BHXH) | không có (404) | trang chuyên mục `?CateID=` đọc được; nội dung nạp bằng JS SharePoint | **dùng sau**: cần tìm API danh sách công khai mà trang đang gọi; không vượt JS thử thách |
| chinhphu.vn, xaydungchinhsach.chinhphu.vn | `Allow: /` | chưa thấy mục hỏi đáp công dân ở đường dẫn thường gặp | **tìm tiếp** mục "Hỏi đáp chính sách" |
| baochinhphu.vn | `Allow: /` | mục "Bạn đọc hỏi, Bộ ngành trả lời" chưa định vị | **tìm tiếp** |
| moj.gov.vn (Bộ Tư pháp) | cho phép, trừ `/cms`, `?handler=` | có sitemap | **dùng sau**: mục hỏi đáp pháp luật theo sitemap |
| vbpl.vn, congbao.chinhphu.vn | cho phép, vbpl cấm `/api/`, `/Pages/` | | nguồn văn bản luật (corpus-gap), không phải tình huống |
| quochoi.vn | trả trang JS đặt cookie (thử thách chống bot) | | **không dùng**: phải vượt thử thách |
| pbgdpl.gov.vn | trả trang "từ chối truy cập" cho bot | | **không dùng** |

## Đầu ra

- `data/raw/cases/<nguồn>/<id>.json`: siêu dữ liệu (tên, cấp xét xử, loại án, toà, ngày, URL) và
  toàn văn trích từ PDF.
- Sau khi che PII: `data/scenarios/cases_v1.jsonl`, cùng lược đồ với `recordings_v1.jsonl`, nguồn
  `judgment` hoặc `qa`.
- Văn bản công khai đã ẩn danh nên được dùng tuyến đám mây mức C (Gemini, Dahl) để rút tình huống.
