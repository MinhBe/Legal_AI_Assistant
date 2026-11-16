# Hậu kiểm: việc để sau khi demo chạy đủ

Minh chọn (16/11/2026): ưu tiên ra demo đủ tính năng trước, sửa lỗi và làm gọn sau. Danh sách này
ghi các mục được hoãn hoặc làm tắt, để quay lại dọn sau.

## Mục hoãn trong lộ trình v1.1
| Mục | Vì sao hoãn | Khi quay lại |
|---|---|---|
| G6 bố cục prompt cố định đầu + chi phí theo ca/bậc | Chủ yếu là đo lường, người xem demo không thấy | Khi cần giảm chi phí chạy Dahl hoặc báo cáo chi phí |
| G7 tìm web cho mức C | Cần Minh chọn nhà cung cấp tìm kiếm | Sau khi Minh chọn nhà cung cấp |
| VL2 đo lại e2e trên golden set | Tốn lượt chat; số đo chưa phục vụ demo | Sau demo, chạy qua Dahl |

## Làm tắt cần dọn
- Ollama: ngữ cảnh 8192 đang được gắn thẳng vào tag `qwen2.5:7b` (Modelfile `PARAMETER num_ctx 8192`), vì app
  Ollama trên Windows ghi đè biến `OLLAMA_CONTEXT_LENGTH` bằng cài đặt riêng (32768). `ollama pull qwen2.5:7b` sẽ
  xóa thay đổi này. Cách gọn hơn: đặt "Context length" trong Settings của app Ollama, hoặc dùng tag riêng
  `qwen2.5:7b-8k` và đặt `LOCAL_MODEL`.
- `app/llm/context.py` vá `metrics.submit` từ ngoài (shortcut G2); gộp vào `app/obs/metrics.py`.
- Trạng thái nghỉ của key đám mây chỉ nằm trong bộ nhớ, mất khi khởi động lại api.
- `data/metrics/requests.jsonl`: 3 dòng thử có tên/SĐT giả (Trần Văn Bình) từ trước khi che PII, cùng 3 trace
  Langfuse. Xóa khi Minh đồng ý.
- U8: công tắc "Dùng tài liệu đã duyệt" truyền qua biến module trong `useChat.ts` thay vì props
  (`components/Chat.tsx` ngoài phạm vi contract); chip "có dùng tài liệu tải lên" nằm ở ô soạn câu hỏi, không gắn
  theo từng tin nhắn. Gộp vào props + `Msg.uses_uploads`.
- U8: bộ phân loại câu hỏi chỉ biết 3 văn bản cố định; khi có đoạn khớp từ tài liệu đã duyệt thì bỏ qua kết luận
  "ngoài kho". Gọn hơn: đưa danh sách tài liệu đã duyệt vào prompt phân loại.
- Chạy mức C mặc định qua mô hình 7B trong máy trước; 7B từng trích sai điều luật. Cân nhắc `CLOUD_FIRST_FOR_C=true`.
