# Ghi âm, chép lời tức thì và làm mờ trước khi gửi (voice intake, 20/11/2026)

Minh 20/11/2026: khách và luật sư đính kèm ghi âm hoặc video (kéo thả như Google Drive), hoặc nói
trực tiếp và thấy chữ hiện ngay như chế độ giọng nói của ChatGPT. Trước khi lưu hay gửi đi bất cứ
đâu, người dùng xem từng đoạn nhạy cảm và tự chọn cách làm mờ, rồi đồng ý cho từng mục đích.

## Luồng

1. **Vào:**
   - kéo thả hoặc chọn tệp ghi âm, ghi hình (nhiều tệp, có thanh tiến độ); hoặc
   - bấm micro: trình duyệt thu PCM 16 kHz, gửi qua WebSocket tới máy chủ của ta.
2. **Chép lời:**
   - Trực tiếp: máy chủ cắt theo khoảng lặng (VAD năng lượng), cứ 1 câu hoặc 6 s thì chép
     bằng model nhỏ (`STT_LIVE_MODEL`, mặc định `small`, int8, giới hạn luồng CPU). Kết quả
     trả về dạng `partial` rồi `final`. Mỗi lúc chỉ một luồng trực tiếp.
   - Tệp: chép bằng model của `AUDIO_MODEL`. Tệp dài thì đưa lên Kaggle (`tools/record_inbox.py`).
   - Không dùng Web Speech API của trình duyệt, vì cách đó gửi âm thanh pháp lý tới Google.
3. **Phát hiện nhạy cảm** (`POST /api/intake/detect`, chỉ chạy luật trong máy, không gọi AI ngoài):
   - TÊN, TỔ_CHỨC: theo `spoken_pii`.
   - SĐT, STK, CCCD, ĐỊA_CHỈ.
   - TÌNH_TIẾT: câu nhắc tới sức khoẻ, tiền án tiền sự, đời tư, tình dục, ma tuý, nợ, tôn giáo,
     bạo lực trong gia đình…
   - Mỗi đoạn trả về: id, loại, giá trị, vị trí, gợi ý thay thế.
4. **Người dùng duyệt** từng đoạn:
   - **Thay tên giả** (mặc định). Tên giả nhất quán theo người: "Văn" → "Nguyễn Văn B",
     "Thị" → "Nguyễn Thị B", không rõ thì "Người B". Công ty thành "Công ty X", địa chỉ thành
     "[địa chỉ]", số thành "[số đã ẩn]".
   - **Làm chung chung**: TÌNH_TIẾT thành "[tình tiết nhạy cảm, đã ẩn]".
   - **Giữ nguyên**: khi cần để hiểu vụ việc.
5. **Đồng ý** (hai ô riêng, mặc định chưa tick):
   - (a) dùng để xử lý vụ việc và lập hồ sơ;
   - (b) góp bản ĐÃ CHE vào dữ liệu train.
   - Không tick (a) thì không lưu gì.
6. **Lưu** (`POST /api/intake/submit`):
   - bảng `intake_record`: bản đã áp lựa chọn, đồng ý (a)/(b), thời điểm, số đoạn theo loại và
     lựa chọn;
   - không lưu bản thô, không lưu ánh xạ giá trị gốc;
   - đoạn khách "giữ nguyên" được đánh dấu: bản có đoạn giữ nguyên là mức B, chỉ mô hình trong
     máy xử lý, không gửi AI ngoài;
   - đồng ý (b) và không còn đoạn giữ nguyên thì mới ghi thêm vào `data/intake/train_pool.jsonl`.
7. **Hồ sơ:** bản đã lưu đi tiếp vào phân tích v2.1 (tình tiết, câu hỏi, điều luật, gợi ý).

## API

| Đường dẫn | Việc |
|---|---|
| `WS /api/stt/live` | nhận PCM int16 16 kHz mono; gửi lại `{type: partial/final, text, start, end}` |
| `POST /api/stt/file` | tải tệp ghi âm hoặc ghi hình, trả các đoạn chép lời (chỉ trả về cho người tải, không lưu) |
| `POST /api/intake/detect` | `{text}` → `{spans:[…]}` |
| `POST /api/intake/apply` | `{text, decisions}` → `{text}` (xem trước) |
| `POST /api/intake/submit` | `{text, decisions, consent_case, consent_training, source}` → `{intake_id}` |

## Giới hạn máy nhà khi phát triển

- Model trực tiếp `small` int8, `cpu_threads=2`, một luồng.
- Test dùng model giả, không nạp model thật.
