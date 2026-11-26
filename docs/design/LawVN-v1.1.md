# Tài liệu thiết kế Legal Agentic (bản hợp nhất): tư vấn pháp luật lao động có AI hỗ trợ, một luật sư chịu trách nhiệm

Phiên bản 1.1 · 12/11/2026 · Trạng thái: bản chốt để triển khai theo giai đoạn, đã hợp nhất phần 7B/7C và các đề xuất chốt

> **Ghi chú hợp nhất (v1.0 → v1.1).** Bản này giữ nguyên toàn bộ nội dung v1.0, bổ sung:
> - **Mục 7B** (thẻ mẫu rủi ro và thẻ kỹ thuật lẩn tránh — góc nhìn điều tra) và **mục 7C**
>   (thu thập dữ liệu tư vấn), đặt đúng vào vùng ngoài phạm vi giai đoạn đầu (mục 1), mức tự
>   chủ 0, chuyên gia hình sự duyệt — nhất quán với Rủi ro 7 của chính tài liệu.
> - **Mục 15** (đề xuất chốt cho các thành phần còn treo): mọi chỗ v1.0 ghi "ngưỡng do luật
>   sư đặt", "đề xuất khởi điểm", "cần kiểm tra" được gom lại kèm một giá trị đề xuất cụ thể
>   để luật sư/kỹ thuật phê duyệt, thay vì để trống.
>
> **Ranh giới nội dung (quyết định thiết kế, ghi để xem lại).** Thẻ của hệ thống viết ở
> *lớp nhận diện* — cơ chế, dấu vết, cách phát hiện, hậu quả kèm căn cứ, phản biện hợp pháp.
> Thẻ **không** chứa *lớp tối ưu thực thi* — mẫu câu thay thế để mô tả lại khoản chi, cách
> chia/gom/chọn thời điểm để xuống dưới ngưỡng, mức giá tuyên là "an toàn", thao tác xóa/sửa
> chứng từ. Ranh giới này áp dụng ở **mọi hạng khách**, kể cả VIP, vì lý do nêu ở 7B.10
> Rủi ro 1: giá trị của một văn bản thực thi đi theo văn bản, không theo chứng nhận của người
> đọc. Phần điều tra và phòng vệ được phục vụ đầy đủ bằng lớp nhận diện (7B.12, 7B.5).
>
> Các chỗ `[cần đối chiếu]` là nơi cố ý không điền số điều luật từ trí nhớ; nguồn xác nhận là
> kho văn bản qua `resolve()`. Đề xuất ở mục 15 là đề xuất kỹ thuật/vận hành, không phải căn
> cứ pháp lý.

---

## 1. Mục tiêu, phạm vi và nguyên tắc

**Mục tiêu.** AI làm gần như toàn bộ lao động chuẩn bị: tiếp nhận, tra cứu, tính toán, soạn
thảo. Một luật sư giữ ba việc: ký và đại diện, duyệt ca rủi ro cao, kiểm mẫu ngẫu nhiên. Mức
tự chủ của AI tăng dần theo từng loại ca dựa trên số liệu đo được, và tụt ngay khi có lỗi
nghiêm trọng.

**Điểm xuất phát.** Hệ thống hiện tại (Legal Agentic v0) còn nhỏ: hàm `law_as_of(date)`, ba văn bản
(BLLĐ 2019, BLLĐ 2012, NĐ 145/2020), 18 câu mẫu, 146 test, 150 bản án, embedding tự host và
cơ chế gửi một câu hỏi tới nhiều LLM cùng lúc. Tài liệu này coi v0 là nền. Mọi thứ khác là
phần cần thêm, xếp theo thứ tự ưu tiên để một người xây được từng bước (xem mục 12).

**Phạm vi giai đoạn đầu.** Pháp luật lao động: hợp đồng lao động, kỷ luật, sa thải, trợ cấp,
xử phạt hành chính trong lĩnh vực lao động. Ngoài phạm vi: tố tụng, hình sự, các lĩnh vực
luật khác. Câu hỏi ngoài phạm vi phải bị từ chối đúng cách hoặc chuyển luật sư.

> **Lưu ý phạm vi cho 7B/7C.** Nhóm quà tặng – hối lộ – điều tra nằm **ngoài** phạm vi giai
> đoạn đầu. 7B/7C được đặc tả ở đây để sẵn sàng cho giai đoạn sau, nhưng cho tới khi có luật
> sư chuyên môn hình sự phụ trách, loại ca này **chỉ chạy ở mức tự chủ 0** và mặc định từ chối
> hoặc chuyển người theo cơ chế ngoài phạm vi (mục 9.1).

**Tám nguyên tắc thiết kế.**

1. Code quyết định thời gian. LLM không tự suy ra ngày hiệu lực.
2. Phân loại dữ liệu trước, chọn mô hình sau.
3. Chạy tầng rẻ trước, leo thang khi độ chắc thấp, rủi ro cao hoặc Verifier báo lỗi.
4. Mọi trích dẫn được kiểm bằng code: điều luật tồn tại, có hiệu lực tại ngày sự kiện, đoạn
   trích khớp nguyên văn.
5. Không thay đổi prompt, mô hình hay dữ liệu nào vào nhánh chính nếu chưa qua cổng eval.
6. Mỗi quyết định của luật sư là một mẫu học và được ghi log.
7. Tự chủ tính theo loại ca, không tính cho toàn hệ thống.
8. Điều gì hệ thống không chắc thì phải nói rõ và chuyển cho người.

## 2. Hiện trạng và khoảng cách

| Mảng | Repo có (theo README) | Còn thiếu | Ưu tiên |
| --- | --- | --- | --- |
| Hiệu lực | `law_as_of(date)`, chuỗi BLLĐ 2012 → 2019 | Tách ngày sự kiện khỏi ngày tư vấn; điều khoản chuyển tiếp; hiệu lực dây chuyền của văn bản hướng dẫn; nhãn "đang chờ sửa đổi" | Cao nhất |
| Kho văn bản | BLLĐ 2019, BLLĐ 2012, NĐ 145/2020 | Nhiều văn bản lao động đã đổi hoặc mới ra (mục 2.3) | Cao |
| Duyệt người thật | Kích hoạt khi câu hỏi ngoài kho văn bản | Kích hoạt theo rủi ro, gói ca, bốn hành động của luật sư, ghi log để học | Cao |
| Dữ liệu ra ngoài | Embedding tự host | Che PII, phân mức dữ liệu, danh sách nhà cung cấp theo mức | Cao (pháp lý) |
| Đo lường | 18 câu mẫu, 146 test | Golden set lớn, có nhóm ca "bẫy thời gian" | Cao |
| Án lệ | 150 bản án từ Hugging Face | Thẻ án lệ, tách án lệ chính thức khỏi bản án thường, cờ trạng thái | Giữa |
| Intake | Tách câu hỏi dài (trên 60 từ) thành 2–4 vấn đề | Bảng sự kiện có cấu trúc, câu hỏi lại, máy tính bằng code | Giữa |

### 2.1 Bảo mật (xử lý ngay)

Image `lawvn-api:1.0` được ghi là đã có sẵn khóa Dahl. Khóa nằm trong image thì ai tải image
về cũng trích ra được. Việc cần làm:

1. Thu hồi khóa đó và cấp khóa mới.
2. Chuyển sang nạp khóa lúc chạy (biến môi trường hoặc kho bí mật), không phát hành lại image cũ.
3. Chạy gitleaks hoặc công cụ tương đương trên toàn bộ lịch sử commit, gồm cả file
   `sync2.bundle`. Một git bundle chứa cả lịch sử nên khóa cũ có thể nằm trong đó. Tác giả tài
   liệu chưa xem nội dung file này.
4. Thêm bước quét bí mật vào CI để lỗi này không lặp lại.

### 2.2 Đua LLM song song mâu thuẫn mục tiêu dữ liệu

README ghi mỗi câu hỏi được gửi đồng thời tới nhiều model và lấy câu hợp lệ nhanh nhất. Hệ quả:

- Dữ liệu của một câu hỏi đi tới nhiều nhà cung cấp cùng lúc.
- Chi phí nhân lên theo số model.
- "Hợp lệ sớm nhất" thưởng cho câu nhanh và ngắn, không thưởng cho câu đúng hơn. Điều kiện hợp
  lệ hiện tại (JSON đúng, tiếng Việt, trích dẫn nằm trong kết quả truy xuất) kiểm được cấu
  trúc và nguồn, chưa kiểm được lập luận đúng hay sai.

Giải pháp ở mục 4: thay đua song song bằng leo thang tuần tự trong danh sách nhà cung cấp của
từng mức dữ liệu. Nên đọc điều khoản dữ liệu của từng nhà cung cấp, nhất là gói miễn phí.

### 2.3 Kho văn bản đã lỗi thời ngay trong lĩnh vực lao động

README ghi hỏi "hiện tại" thì ra BLLĐ 2019 và NĐ 145. Theo các nguồn đã tra ở các lượt trước
(cần đối chiếu bản gốc trước khi nạp):

- Nghị định 283/2026/NĐ-CP (ban hành 15/7/2026) thay Nghị định 12/2022 về xử phạt vi phạm
  hành chính lĩnh vực lao động, áp dụng từ 10/9/2026.
- Nghị định 337/2025/NĐ-CP có hiệu lực từ 1/1/2026, hướng dẫn việc sửa đổi, tạm hoãn, chấm dứt
  hợp đồng lao động điện tử.
- Luật Việc làm 2013 hết hiệu lực từ 1/1/2026, do Luật Việc làm 2025 thay thế.
- Bộ Nội vụ đang lấy ý kiến dự thảo nghị định sửa đổi NĐ 145/2020.
- Một bảng so sánh dự thảo viện dẫn một luật sửa đổi Bộ luật Lao động và ba luật khác, số hiệu
  năm 2026 còn để trống. Cần kiểm tra luật này đã được thông qua chưa.

Câu hỏi kiểu "công ty phạt tiền thay kỷ luật thì bị phạt bao nhiêu" sẽ trả lời sai hoặc thiếu
nếu chỉ có ba văn bản hiện tại. Đây cũng là minh chứng tốt cho bài toán thời gian.

### 2.4 Kết quả 18/18 chưa chứng minh nhiều

Với 18 câu tự soạn, nếu 0 câu sai thì theo quy tắc 3/n, tỷ lệ lỗi thật vẫn có thể lên tới
khoảng 17% ở độ tin cậy 95%. Chỉ số "đúng Điều trích dẫn" chỉ đo truy xuất và trích dẫn, chưa
đo đúng sai pháp lý. Cách đo thay thế nằm ở mục 11.

## 3. Kiến trúc tổng thể

Hệ thống chia hai vùng. **Vùng nội bộ** gồm Data Gateway, bảng ánh xạ tên thật, embedding,
reranker, kho văn bản, log và mô hình tự host. **Vùng ngoài** là các nhà cung cấp LLM trong
danh sách cho phép và tìm web. Mọi dữ liệu đi qua một cổng duy nhất để quyết định ở lại hay ra
ngoài. Mọi kết quả đều đổ về một luật sư.

| Thành phần | Vai trò | Dùng LLM? | Vùng |
| --- | --- | --- | --- |
| Data Gateway | Phân loại A/B/C, che PII, giữ bảng ánh xạ | Regex và mô hình nhỏ tự host | Nội bộ |
| Intake | Tách vấn đề, dựng bảng sự kiện, hỏi lại khi thiếu | Mô hình rẻ | Nội bộ (mức A) hoặc ngoài (mức B) |
| Temporal Resolver | Giải phiên bản luật theo ngày sự kiện và ngày tư vấn | Không, code thuần | Nội bộ |
| Retrieval | Embedding, rerank xuống top-5 | Mô hình tự host | Nội bộ |
| Calculators | Thời hạn, trợ cấp, thời hiệu, mức phạt | Không, code thuần | Nội bộ |
| LLM Router | Chọn tầng và nhà cung cấp theo mức dữ liệu, leo thang | Có | Nội bộ điều phối |
| Verifier | Kiểm trích dẫn, hiệu lực, bốn loại lỗi AI pháp lý | Code cộng mô hình mạnh cho ca rủi ro cao | Nội bộ hoặc ngoài (mức B) |
| Bộ chấm rủi ro | Quyết định gửi theo mức tự chủ hay đưa vào hàng đợi luật sư | Quy tắc, sau này thêm classifier | Nội bộ |
| Bàn duyệt luật sư | Gói ca, bốn hành động, ghi log | Không | Nội bộ |
| Cổng eval | Chạy golden set, chặn thay đổi không đạt | Có | Nội bộ |

**Luồng một ca, từ đầu đến cuối.**

1. Khách gửi câu hỏi hoặc hồ sơ.
2. Data Gateway phân loại mức dữ liệu, che PII, tạo bảng ánh xạ (ở lại nội bộ).
3. Intake tách vấn đề, dựng bảng sự kiện gồm ngày sự kiện và ngày tư vấn, hỏi lại khi thiếu
   trường quyết định.
4. Temporal Resolver giải phiên bản luật áp dụng và dựng khối khung thời gian.
5. Retrieval lấy điều luật, thẻ án lệ, mẫu; rerank còn top-5.
6. Calculators tính các con số bằng code.
7. LLM Router chọn tầng mô hình, soạn câu trả lời có trích dẫn.
8. Verifier kiểm bằng code, rồi bằng mô hình nếu ca rủi ro cao.
9. Bộ chấm rủi ro quyết định: gửi theo mức tự chủ của loại ca, hoặc đưa vào hàng đợi luật sư.
10. Luật sư duyệt (nếu có). Tên thật được gắn lại ở nội bộ, kết quả gửi khách, toàn bộ vết
    được ghi log.

**Phân tầng mô hình để tiết kiệm token.**

| Tầng | Việc làm |
| --- | --- |
| Code và quy tắc, không dùng LLM | Giải phiên bản luật theo ngày, tính thời hiệu, lương, trợ cấp, kiểm tra trích dẫn có tồn tại, regex PII |
| Mô hình rẻ (API yếu hoặc tự host) | Phân loại, trích xuất sự kiện thành JSON, phát hiện PII, viết lại truy vấn, rerank, gắn nhãn hàng loạt |
| Mô hình trung | Trả lời có trích dẫn từ RAG, soạn từ mẫu, viết bản tư vấn theo ngôn ngữ khách |
| Mô hình mạnh (reasoning) | Thẻ án lệ, so khớp án lệ với ca, xử lý chuyển tiếp thời gian, phương án chiến lược, văn bản phức tạp, Verifier cho ca rủi ro cao |

Quy tắc leo thang: chạy tầng thấp trước, lên tầng cao khi độ chắc thấp, rủi ro cao hoặc
Verifier báo lỗi. Kỹ thuật tiết kiệm chính: tính trước thẻ án lệ; prompt caching cho phần luật
cố định; chạy batch khi nạp dữ liệu; rerank xuống top-5 trước khi đưa vào mô hình mạnh; đo chi
phí theo từng ca và từng tầng để chỉnh ngưỡng.

## 4. Data Gateway và phân mức dữ liệu

Quy tắc: phân loại dữ liệu trước, rồi mới chọn mô hình.

| Mức | Ví dụ | Xử lý ở đâu |
| --- | --- | --- |
| A: định danh, bí mật nghề nghiệp | Lời kể, hồ sơ, hợp đồng của khách | Chỉ LLM tự host. Không ra ngoài. Nếu không có mô hình tự host đủ sức thì từ chối hoặc chuyển luật sư |
| B: sự kiện pháp lý đã che | "Lao động A, lương X, HĐ không thời hạn, bị sa thải ngày D" | Có thể gọi LLM ngoài cho tác vụ khó, chỉ qua danh sách nhà cung cấp cho phép |
| C: không có dữ liệu cá nhân | Câu hỏi luật chung, tra văn bản công khai | Ra ngoài tự do, gồm cả tìm web |

**Cơ chế đi kèm.**

- Thêm tham số `data_class` (A, B, C) cho LLM Router. Mỗi lớp có danh sách nhà cung cấp được
  phép. Lớp A chỉ vào model tự host hoặc bị từ chối.
- Che PII xảy ra trước router, không phải sau.
- Bảng ánh xạ giữa tên thật và mã che nằm trong vùng nội bộ. Việc gắn lại tên thật chỉ làm ở trong.
- Embedding và reranker chạy nội bộ, để nội dung vụ việc không rời hệ thống khi truy xuất.
- Truy vấn tìm web chỉ sinh từ dữ kiện đã che, không chứa tên hay số tiền thật.
- Chuyển mức A ra ngoài chỉ qua "mở khóa khẩn" do luật sư duyệt từng lần và có log.
- Mức B vẫn được coi là dữ liệu cá nhân, vì dữ liệu đã che vẫn có thể bị tái định danh.

**Thay đua song song bằng leo thang.** Thứ tự thử: mô hình rẻ, rồi mô hình trung, rồi mô hình
mạnh, dừng ngay khi Verifier đạt. Không gửi cùng lúc cho nhiều nhà cung cấp. Đua song song chỉ
còn được dùng ở chế độ eval với dữ liệu mức C, để so sánh chất lượng giữa các model, không
dùng trên lưu lượng thật.

**Pháp lý (cần đối chiếu văn bản gốc).** Theo nguồn đã tra, Nghị định 356/2025 có hiệu lực từ
1/1/2026, thay Nghị định 13/2023, và yêu cầu hồ sơ đánh giá tác động chuyển dữ liệu xuyên biên
giới khi chuyển dữ liệu cá nhân ra nước ngoài. Hồ sơ đánh giá tác động xử lý và chuyển dữ liệu
phải cập nhật định kỳ 6 tháng một lần, hoặc khi có mục đích hay thay đổi mới. Mỗi nhà cung cấp
LLM ngoài cần một dòng trong hồ sơ này, nhất là khi máy chủ ở nước ngoài. Nghị định 330 quy
định chế tài khi không tuân thủ.

## 5. Mô hình pháp lý theo thời gian

Luật sư không chỉ hỏi "luật còn hiệu lực không" mà tách thành nhiều mốc. Hệ thống phải lưu và
truy vấn đủ các mốc sau.

| Mốc | Vì sao quan trọng |
| --- | --- |
| Ngày thông qua | Một luật có thể hết hiệu lực từng phần vào các ngày khác nhau. Ví dụ: khi Luật Ban hành VBQPPL 2025 thay luật cũ, một khoản của luật cũ hết hiệu lực ngay từ ngày luật mới được thông qua, phần còn lại từ ngày luật mới có hiệu lực |
| Ngày có hiệu lực, tính theo từng điều | Luật Xây dựng 2025 có hiệu lực từ 1/7/2026 nhưng một số điều có hiệu lực từ 1/1/2026 |
| Ngày hết hiệu lực hoặc bị thay | Luật Việc làm 2013 hết hiệu lực ngày 1/1/2026. Khi văn bản gốc hết hiệu lực, văn bản hướng dẫn cũng hết theo, với một số ngoại lệ |
| Ngày sự kiện (ký hợp đồng, sa thải, vi phạm) | Nguyên tắc chung: hành vi xảy ra thời điểm nào thì áp dụng pháp luật thời điểm đó, trừ khi luật mới ghi rõ có hiệu lực trở về trước. Còn có ngoại lệ có lợi và điều khoản chuyển tiếp. Với hợp đồng, hướng dẫn của Hội đồng Thẩm phán về BLDS 2015 phân biệt hợp đồng đã thực hiện xong, chưa thực hiện và đang thực hiện |
| Ngày tư vấn | Quyết định có cần cảnh báo về thay đổi sau sự kiện hay không |
| Ngày luật sắp đổi | Ví dụ: Bộ Tư pháp đề xuất sửa Luật Ban hành VBQPPL, dự kiến có hiệu lực từ 1/3/2027. Cần kiểm tra tiến độ thực tế |
| Ngày hệ thống biết (thời điểm nạp) | Để sau này chứng minh hệ thống đã biết gì lúc tư vấn |

Bản thân luật về cách áp dụng luật cũng đổi. Luật Ban hành VBQPPL 2025 (64/2025/QH15) có hiệu
lực từ 1/4/2025 và thay luật 2015, nên số điều trong tài liệu cũ có thể không còn khớp. Quyết
định 41/2026 bãi bỏ 66 văn bản của Thủ tướng từ 1/10/2026. Văn bản cấp huyện được kéo dài hiệu
lực đến hết tháng 2/2027. Các ví dụ này lấy từ nguồn đã tra, cần đối chiếu trước khi dùng làm
căn cứ.

### 5.1 Lược đồ dữ liệu: mở rộng `node_supersession` thành ba bảng

**Bảng `provision_version`** (mỗi điều, khoản, điểm có nhiều phiên bản):

| Trường | Ý nghĩa |
| --- | --- |
| provision_key | Khóa điều, khoản, điểm |
| text, hash, source_url | Nội dung, hash nội dung, nguồn gốc |
| valid_from, valid_to | Hiệu lực theo từng điều, không theo cả văn bản |
| status | hiệu lực; hiệu lực một phần; đang chờ sửa đổi; chưa hiệu lực; bãi bỏ |
| adopted_on | Ngày thông qua |
| amended_by | Văn bản sửa đổi |
| known_from, known_to | Khoảng thời gian hệ thống biết phiên bản này |

**Bảng `transition_rule`** (điều khoản chuyển tiếp):

| Trường | Ý nghĩa |
| --- | --- |
| doc_key | Văn bản chứa điều khoản chuyển tiếp |
| condition | Giao kết trước ngày X; đã thực hiện xong, đang thực hiện hay chưa thực hiện |
| outcome | Áp dụng luật cũ, luật mới, hoặc hỗn hợp |
| provision_ref, note | Điều áp dụng và ghi chú |

**Bảng `legal_link`** (đồ thị quan hệ): `from_key`, `to_key`, `link_type` (hướng dẫn, sửa đổi,
thay thế, viện dẫn, dựa trên), `valid_from`, `valid_to`.

### 5.2 Hàm `resolve(event_date, advice_date)`

Làm bốn bước, hoàn toàn bằng code:

1. Lấy phiên bản có hiệu lực tại **ngày sự kiện**. `law_as_of` hiện có làm phần này, nhưng
   phải được gọi với ngày sự kiện, không phải ngày hôm nay.
2. Nếu có văn bản mới hơn thì tra `transition_rule`. Nếu không có quy tắc, áp nguyên tắc luật
   tại thời điểm sự kiện và gắn cờ "cần luật sư xác nhận" cho lĩnh vực xử phạt.
3. Lấy các thay đổi sau ngày sự kiện đến ngày tư vấn, đưa vào cảnh báo.
4. Lấy phiên bản chờ hoặc dự thảo, đưa vào mục "sắp thay đổi". Mục này không được dùng làm căn cứ.

**Khối khung thời gian** có mặt trong mọi bản tư vấn: luật áp dụng vì sự kiện ngày D; thay đổi
sau đó; thay đổi sắp tới; điều khoản chuyển tiếp đã xét.

**Ví dụ.** Sa thải ngày 20/12/2020, tư vấn ngày 12/11/2026: resolver chọn BLLĐ 2012 (luật tại
ngày sự kiện), nêu BLLĐ 2019 từ 1/1/2021 trong mục thay đổi sau sự kiện, và LLM không được tự
quyết định luật nào áp dụng. Ca vi phạm hành chính sát mốc 10/9/2026 luôn mang cờ "cần luật sư
xác nhận" nếu chưa có quy tắc chuyển tiếp rõ.

### 5.3 Hiệu lực dây chuyền, cờ trạng thái và vận hành

- Khi một văn bản gốc bị thay, `legal_link` tự đánh dấu các nghị định hướng dẫn, thẻ án lệ và
  mẫu hợp đồng dựa vào nó là "cần xác minh". Hệ thống không tự bãi bỏ chúng, vì có ngoại lệ.
- Nếu ngày nạp của văn bản mới nhất đã cũ quá ngưỡng thì thêm cờ "có thể chưa cập nhật", vì
  nguồn chính thức cũng có độ trễ. Ngưỡng do luật sư đặt (đề xuất khởi điểm 30 ngày).
- Verifier chặn mọi điều luật viện dẫn không hiệu lực tại ngày sự kiện. Ca đó tự chuyển về luật sư.
- Theo dõi công báo hằng ngày. Mỗi khi nạp văn bản mới phải chạy lại golden set, nhóm "bẫy
  thời gian" trước tiên.
- Mỗi bản tư vấn lưu ngày và phiên bản nguồn đã dùng, để chứng minh kết quả nghiên cứu khi cần.

Các kho luật và công cụ nước ngoài dùng cùng ý tưởng: legislation.gov.uk cho xem bản tại một
ngày bất kỳ và có phiên bản "prospective"; Westlaw UK dùng nhãn đang hiệu lực, hiệu lực một
phần, đang hiệu lực kèm sửa đổi chờ áp dụng, chưa hiệu lực, đã bãi bỏ; Shepard's và KeyCite
đánh dấu án và luật không còn là "good law".

## 6. Kho văn bản: danh mục nạp ưu tiên

| Văn bản | Trạng thái kho | Việc cần làm |
| --- | --- | --- |
| BLLĐ 2019 (45/2019/QH14) | Đã có | Thêm `valid_from/valid_to` theo từng điều. Kiểm tra luật sửa đổi 2026 đã thông qua chưa |
| BLLĐ 2012 (10/2012/QH13) | Đã có | Dùng cho sự kiện trước 1/1/2021 |
| NĐ 145/2020/NĐ-CP | Đã có | Gắn `legal_link` "hướng dẫn" BLLĐ 2019. Theo dõi dự thảo sửa đổi, đưa vào mục "sắp thay đổi" |
| NĐ 12/2022/NĐ-CP | Chưa có | Nạp, đặt hiệu lực đến trước 10/9/2026 |
| NĐ 283/2026/NĐ-CP | Chưa có | Nạp, áp dụng từ 10/9/2026. Ưu tiên cao cho câu hỏi về mức phạt |
| NĐ 337/2025/NĐ-CP | Chưa có | Nạp, hiệu lực từ 1/1/2026, hợp đồng lao động điện tử |
| Luật Việc làm 2013 và 2025 | Chưa có | Nạp cả hai, mốc 1/1/2026, dùng cho câu hỏi trợ cấp thất nghiệp |
| Dự thảo sửa NĐ 145/2020 | Chưa có | Chỉ gắn trạng thái "chưa hiệu lực", không làm căn cứ |
| Luật sửa đổi BLLĐ và ba luật khác (2026) | Cần kiểm tra | Số hiệu còn trống. Xác minh đã thông qua chưa rồi mới quyết định nạp |

**Quy trình nạp một văn bản:** tải bản gốc từ nguồn chính thống; ghi nguồn và hash; tách điều,
khoản; gán hiệu lực theo từng điều; khai báo `legal_link` và `transition_rule`; luật sư duyệt;
chạy golden set; rồi mới đưa vào nhánh chính. Với thay đổi nội dung pháp lý, luật sư luôn là
người duyệt, không giao cho cổng eval tự quyết.

## 7. Án lệ và thẻ án lệ

**Hai tầng nguồn.** Ở Việt Nam, Tòa án nhân dân tối cao đã công bố 90 án lệ tính đến tháng
7/2026 (theo nguồn đã tra). Án lệ có giá trị bắt buộc có điều kiện, không theo học thuyết
stare decisis của thông luật, và không được áp dụng khi tình hình thay đổi mà không còn phù
hợp. Vì vậy chia hai tầng:

- **Án lệ chính thức:** ít, có cấu trúc, đáng đầu tư mô hình mạnh. Giai đoạn đầu chỉ làm các án
  lệ liên quan lao động.
- **Bản án thường (150 bản án hiện có):** nhiều, không ràng buộc, chỉ để tham khảo, cần thêm
  cột kết quả kháng cáo, hủy hoặc sửa. Cần ghi rõ nguồn và điều khoản sử dụng của bộ dữ liệu
  trên Hugging Face.

**Tạo thẻ án lệ (offline).** Mô hình mạnh đọc từng án lệ một lần, chạy batch, luật sư kiểm mẫu.
Thẻ gồm: tình tiết then chốt; vấn đề pháp lý; giải pháp pháp lý; điều luật nền kèm phiên bản
hiệu lực lúc xét xử (nối `legal_link`); điều kiện áp dụng; yếu tố làm khác biệt; trạng thái.
Trạng thái tự suy ra từ điều luật nền: nếu điều luật đó đã bị thay thì thẻ gắn cờ.

**Dùng thẻ khi tư vấn.** Truy xuất thẻ rất rẻ. Mô hình mạnh chỉ làm một việc: so tình tiết của
khách (đã che) với 3–5 thẻ, chỉ ra giống ở đâu, khác ở đâu và rủi ro nằm ở đâu.

**Kiểm bằng code.** Số hiệu án lệ phải tồn tại trong kho. Đoạn trích phải khớp nguyên văn.

**Bốn loại lỗi Verifier phải kiểm.** Nghiên cứu của Stanford về công cụ AI pháp lý chỉ ra:
viện dẫn án không liên quan hoặc đã bị đảo; gán sai nhận định cho tòa; nhầm lập luận của bên
với phán quyết; xu nịnh (đồng ý với người dùng dù người dùng sai). Tỷ lệ lỗi báo cáo: các công
cụ pháp lý hàng đầu ở Mỹ từ 17% đến 33%, GPT-4 là 43%, và thay đổi theo khu vực pháp lý. Luật
Việt Nam có ít dữ liệu hơn, nên suy luận hợp lý là tỷ lệ lỗi sẽ cao hơn nếu không có RAG và
Verifier. Đây là suy luận, cần đo bằng golden set của chính hệ thống.

---

## 7B. Thẻ mẫu rủi ro và thẻ phương án từ tư liệu thực tiễn (ngoài phạm vi giai đoạn đầu)

> **Vị trí và điều kiện vận hành.** Nhóm quà tặng – hối lộ – điều tra nằm ngoài phạm vi giai
> đoạn đầu (mục 1). Phần này đặc tả để sẵn sàng cho giai đoạn sau. Cho tới khi có luật sư
> chuyên môn hình sự phụ trách, loại ca này **chỉ chạy ở mức tự chủ 0**, và trong giai đoạn 1–5
> hệ thống **từ chối hoặc chuyển người** theo cơ chế ngoài phạm vi.

### 7B.1 Mục đích và nguyên tắc

Tư liệu thực tiễn (ví dụ livestream phiên tòa, bình luận luật sư, lời kể) dùng để học cách
tình huống thực tế diễn ra: đối tác tạo thế thế nào, vùng xám ở đâu, bên kiểm tra nhìn vào
đâu, hậu quả ra sao. Đầu ra là gói tham khảo cho luật sư, không phải bản án và không phải căn
cứ pháp lý.

Mỗi thẻ trả lời năm câu: cơ chế hoạt động thế nào; để lại dấu vết gì; bị phát hiện ra sao; hậu
quả theo từng bước và từng vai kèm căn cứ; thân chủ làm gì được một cách hợp pháp (thu thập
chứng cứ, phòng thủ, đấu tranh lâu dài).

### 7B.2 Ranh giới nội dung: hai lớp phải tách

Một "dấu hiệu phía thực thi" gồm hai lớp **phải tách rời** (xem lại Ghi chú hợp nhất đầu tài
liệu). Phép thử một dòng cho mỗi câu chữ: *câu này giúp người đọc nhận ra và chứng minh hành
vi, hay giúp họ thực hiện trót lọt hành vi?*

| Lớp nhận diện (RÚT VÀO THẺ, càng sâu càng tốt) | Lớp tối ưu thực thi (KHÔNG rút, mọi hạng khách) |
| --- | --- |
| Cơ chế mẫu và vì sao nó tồn tại | Mẫu câu thay thế để mô tả lại khoản chi |
| Dấu hiệu nhận biết, dấu vết để lại | Cách chia/gom/chọn thời điểm để xuống dưới ngưỡng |
| Bản đồ dấu vết: chứng cứ nào có, bên kiểm tra truy bằng gì | Mức giá cụ thể được ghi là "an toàn" |
| Phân tích hậu quả và căn cứ theo từng bước, từng vai | Thao tác xử lý chứng từ, tin nhắn để che dấu vết |
| Bằng chứng nên thu thập và cách bảo toàn hợp pháp | Cách phản kiểm tra, né điều tra |
| Cách từ chối, ghi nhận, báo cáo, giữ bằng chứng | Bước làm cho hồ sơ "trông sạch" |
| Chiến lược phản biện hợp pháp, đấu tranh dài hạn | |

Lý do lớp phải bị cắt kể cả với khách VIP là lập luận 7B.10 Rủi ro 1: một văn bản thực thi có
cùng giá trị với bất kỳ ai cầm nó; kiểm chứng đạo đức *người đọc* không giảm giá trị của *văn
bản* khi nó rò rỉ, bị ép giao hay người đọc đổi vai. Lớp nhận diện không cần cổng vì nó phục
vụ phát hiện và phòng vệ, không phục vụ thực thi. Với bên điều tra: điều tra viên cần chữ ký và
dấu vết, không cần công thức tối ưu của tội phạm — lớp nhận diện cho họ nhiều hơn.

### 7B.3 Luồng nạp

1. Nguồn có phép. Ghi giấy phép, người nói, ngày, loại tư liệu. Luật sư xem điều khoản nền
   tảng và bản quyền trước khi thu thập.
2. ASR/OCR tự host, giữ mốc thời gian. Ngày, số tiền, số điều coi là độ chắc thấp, không tự dùng.
3. Che PII ngay sau transcript, trước mọi LLM ngoài. Audio/transcript gốc ở mức A hoặc xóa sau
   khi trích xuất.
4. Trích xuất (mô hình rẻ): tình huống, hành vi, bên liên quan, kết quả được kể. Nếu nguồn
   chứa lớp tối ưu thực thi thì **chuyển hóa thành chữ ký nhận diện + bản đồ dấu vết, bỏ tham
   số tối ưu**, ghi log.
5. Gom mẫu (mô hình trung, batch): mỗi mẫu cần tối thiểu 2 nguồn độc lập mới lên thẻ chính thức.
6. Đối chiếu pháp lý bằng `resolve(event_date, advice_date)`: căn cứ phải khớp kho và đúng
   phiên bản theo ngày sự kiện. Không khớp thì gắn cờ.
7. Verifier và bộ lọc ranh giới (7B.8).
8. Luật sư (chuyên môn hình sự) duyệt. Cổng eval không tự quyết.

**Mức tin cậy theo loại nguồn:** phiên tòa phát trực tiếp (cao hơn, vẫn đối chiếu bản án gốc);
luật sư bình luận (trung bình, là ý kiến); người dân kể (thấp, một phía, chỉ để phát hiện mẫu).

### 7B.4 Schema và bảng phân tích theo từng bước

**Thẻ mẫu rủi ro** (một mẫu hành vi): pattern_id và tên trung tính; cơ chế (mức nhận diện); vì
sao tồn tại (`provision_key` nếu có); dấu hiệu nhận biết; bản đồ dấu vết (7B.5a); cách bị phát
hiện; **bảng phân tích theo từng bước**; hậu quả theo vai; vai thân chủ; kế hoạch chứng cứ và
phòng thủ (7B.5b, 7B.5c); nguồn/người nói/ngày/độ tin cậy/số nguồn độc lập; trạng thái.

**Bảng phân tích theo từng bước** (bắt buộc, mỗi hành vi một dòng):

| Hành vi (mô tả trung tính) | Dấu vết để lại | Bên kiểm tra truy bằng | Căn cứ pháp luật (qua `resolve()`) | Hậu quả theo vai |
| --- | --- | --- | --- | --- |
| (điền theo ca) | (chứng cứ) | (phép đối chiếu) | `provision_key` + phiên bản [cần đối chiếu] | người cho / nhận / trung gian / tư vấn |

Thiếu cột căn cứ hoặc cột hậu quả thì thẻ không phát hành. Căn cứ chưa xác minh ghi rõ "chưa
xác minh", không điền số điều từ trí nhớ.

**Thẻ phương án** (một hướng xử lý): mục tiêu thật của thân chủ; hành động; căn cứ qua
`resolve()`; đạt được gì; cái giá; rủi ro khi hậu kiểm; điều kiện để hướng đó an toàn; nhãn
vùng xám nếu có; gợi ý cách nói với thân chủ; cờ ranh giới. Mỗi ca thường có 3–5 thẻ phương
án, trong đó ít nhất một là đường sạch.

### 7B.5 Ba phần cho bên hành pháp, bên cạnh tranh và bên bị cáo buộc

**7B.5a Bản đồ dấu vết** (thẻ nào cũng có): với mỗi hành vi, liệt kê nhóm chứng cứ (tài chính,
liên lạc, hệ thống nội bộ, quan hệ lợi ích, nhân chứng, tính nhất quán), ai giữ, truy bằng
cách nào. Cho bên hành pháp biết tìm gì ở đâu; cho thân chủ thấy dấu vết thật sự nhiều đến mức nào.

**7B.5b Kế hoạch bảo toàn và thu thập chứng cứ** (bên tố cáo, bên bị kéo vào, bên đối địch):
giữ bản gốc không chỉnh sửa, lập hash, ghi chuỗi lưu giữ; dựng dòng thời gian từ chính chứng
cứ; giữ các phiên bản lời giải thích khác nhau của đối phương kèm nguồn và ngày; chọn kênh báo
cáo đúng thẩm quyền và ghi nhận bằng văn bản [cần đối chiếu quy định bảo vệ người tố cáo];
**kiểm tra tính hợp pháp của cách thu thập trước khi dùng** — ghi âm, truy cập tài khoản/thiết
bị người khác, chụp tài liệu nội bộ đều có thể làm chứng cứ bị loại hoặc tự gây rủi ro pháp lý
cho người thu thập; luật sư duyệt cách thu thập trước khi thân chủ hành động [cần đối chiếu].

**7B.5c Chiến lược phản biện hợp pháp** (bên bị cáo buộc hoặc đang bị kiểm tra): làm rõ sự thật
bằng chứng cứ thật (giá trị, bối cảnh, mục đích); tách các yếu tố cấu thành (thẩm quyền, mối
liên hệ với quyết định, chủ ý, giá trị) — mỗi yếu tố bên buộc tội đều phải chứng minh; phản
biện chứng cứ phía kia (nguồn gốc, toàn vẹn, cách thu thập, nhất quán, thời hiệu); quyền của
người bị kiểm tra/điều tra [cần đối chiếu]; khắc phục minh bạch từ hiện tại (khai báo, hoàn
trả, báo tuân thủ) — thường là bước giảm hậu quả nhất; **tuyệt đối không xóa, sửa, tiêu hủy,
giấu chứng cứ sau khi biết có kiểm tra** — hành vi đó có thể là vi phạm riêng, thường nặng hơn
[cần đối chiếu], luật sư không hướng dẫn việc này.

**Ranh giới "phòng vệ" vs "che giấu".** Phòng vệ hợp pháp = chứng minh hành vi vốn hợp pháp +
giữ hồ sơ minh bạch + khắc phục từ hiện tại. Nó không bao gồm làm mỏng dấu vết của hành vi có
vấn đề; việc đó là che giấu/cản trở. Hệ thống không tạo đầu ra thuộc nhóm thứ hai, kể cả khi
đóng khung là "giúp thân chủ phòng bị".

### 7B.6–7B.7 Thẻ mẫu (khung)

Hai thẻ mẫu — "giá trị quà tính theo bộ hay theo phần lẻ" và "quà/ưu đãi trong quan hệ cùng
xin dự án" — viết theo đúng schema 7B.4: cơ chế, vì sao tồn tại, dấu hiệu, bản đồ dấu vết, bảng
phân tích từng bước (có căn cứ qua `resolve()` và hậu quả theo vai), và ba phần 7B.5. Mỗi thẻ
**không** chứa danh sách mẫu câu thay thế, mức/số lần chia, mức giá "an toàn" hay thao tác che
chứng từ.

### 7B.8 Bộ lọc ranh giới trong Verifier

Verifier chặn một thẻ nếu chứa bất kỳ yếu tố nào sau đây, **bất kể có kèm cảnh báo hay phân
tích hậu quả hay không**: mẫu câu thay thế để mô tả lại khoản chi; cách chia/gom/chọn thời
điểm để xuống dưới ngưỡng; mức giá ghi là "an toàn"; thao tác xử lý chứng từ/tin nhắn để che
dấu vết; cách phản kiểm tra, né điều tra. Thẻ bị chặn chuyển thành thẻ cảnh báo kèm hướng xử lý
hợp pháp và ghi log. Kiểm ngược trước khi phát hành: mỗi thẻ phải đủ dấu hiệu nhận biết, bản đồ
dấu vết, cách bị phát hiện, bảng phân tích từng bước (có căn cứ và hậu quả) — thiếu một phần
thì không phát hành.

### 7B.9 Chỉ số (bổ sung cho mục 11)

| Chỉ số | Cách đo | Ngưỡng đề xuất |
| --- | --- | --- |
| Lọt thẻ chứa lớp tối ưu thực thi | Bộ ca đối kháng (yêu cầu kịch bản né ngưỡng, yêu cầu thẻ chứa nội dung 7B.8) | 0 (cổng cứng) |
| Thẻ có đủ phần bắt buộc | Kiểm bằng code | 100% |
| Căn cứ đúng phiên bản | Nhóm bẫy thời gian | 100% |
| Mẫu có ≥ 2 nguồn độc lập | Kiểm bằng code | 100% với thẻ chính thức |
| Họ (b),(c) nêu được cả hành vi hợp pháp lẫn vi phạm (chống hình sự hóa cái hợp pháp) | Luật sư chấm mẫu | 100% |

Golden set nhóm 3 (từ chối đúng) thêm 15–20 ca: yêu cầu soạn kịch bản né ngưỡng, mô tả lại
khoản chi, hạ giá trị trên hồ sơ, xử lý chứng từ/tin nhắn — kể cả khi đóng khung là "chỉ để
tham khảo" hay "chỉ cho khách VIP".

### 7B.10 Phân tích rủi ro của chính thiết kế này

1. **Kiến thức phòng thủ cũng là kiến thức tấn công.** Bản đồ dấu vết vẫn có thể bị đọc ngược.
   Giảm thiểu bằng phép thử hướng nhìn (7B.2), bộ lọc 7B.8, không đưa lớp tối ưu vào thẻ; rủi
   ro còn lại không về 0 nên luật sư duyệt từng thẻ.
2. **Áp lực đòi "cụ thể hơn".** Quy tắc: chi tiết hơn ở phía phát hiện, hậu quả, chứng cứ,
   phòng vệ thì cho; chi tiết hơn ở lớp tối ưu thực thi thì không, kể cả khách VIP.
3. **Thân chủ vẫn chọn hướng vi phạm sau khi hiểu hậu quả.** Hệ thống không cản được quyết định
   của thân chủ; luật sư giữ nghĩa vụ nghề nghiệp; hệ thống bảo đảm thân chủ nghe đủ hậu quả và
   có log [cần đối chiếu quy tắc hành nghề, mục 14].
4. **Sai lệch từ nguồn.** Giảm thiểu bằng 2 nguồn độc lập, độ tin cậy theo loại nguồn, không
   dùng số liệu từ tư liệu làm căn cứ.
5. **Pháp lý của chính việc thu thập.** Điều khoản nền tảng, bản quyền, NĐ 356, và việc hệ
   thống có thuộc danh mục AI rủi ro cao (QĐ 33/2026) đều cần xác nhận.
6. **Cảm giác "tự chọn" bị biến thành thao túng.** Cách nói có thể mềm nhưng không được bỏ hoặc
   làm nhẹ cái giá. Luật sư kiểm mẫu, có ca bẫy trong hàng đợi (9.4).
7. **Tư vấn vượt phạm vi.** Nhóm này ngoài phạm vi giai đoạn đầu; chuyển luật sư chuyên môn
   hình sự, chạy ở mức tự chủ 0.
8. **Hướng dẫn thu thập chứng cứ gây hại cho chính thân chủ.** Mọi thẻ có 7B.5b kèm bước luật
   sư duyệt cách thu thập.

### 7B.11 Việc cần xác minh

Điều khoản nền tảng về thu thập tự động và bản quyền; văn bản về cách xác định giá trị quà
tặng, ngưỡng, mức xử lý theo từng đối tượng; văn bản về đưa/nhận/môi giới/che giấu và bảo vệ
người tố cáo; quy định về thu thập và sử dụng chứng cứ hợp pháp; quy tắc hành nghề luật sư khi
thân chủ muốn làm trái pháp luật; hệ thống thuộc mức rủi ro nào theo Luật AI và QĐ 33/2026.

### 7B.12 Thẻ kỹ thuật lẩn tránh — góc nhìn điều tra (thành phần chính cho bên hành pháp)

Đây là nơi chứa phần chi tiết mà bên điều tra và bên phòng vệ cần, viết **từ phía điều tra và
phòng vệ**, không viết từ phía người thực hiện.

**Schema (mỗi kỹ thuật một thẻ):** technique_id và tên trung tính; mô tả nhận diện (đủ để nhận
ra, không ở mức công thức để làm); vì sao tồn tại (`provision_key`); chữ ký/red flags; bản đồ
dấu vết (7B.5a); cách điều tra đối chiếu; **ranh giới pháp lý** (chỗ nào hợp pháp, chỗ nào vượt
sang vi phạm, yếu tố chủ ý); căn cứ qua `resolve()`; hậu quả theo vai; hướng điều tra (cần tìm
gì, ở đâu, theo thứ tự nào, cách bảo toàn giá trị chứng cứ); phản biện hợp pháp (chứng minh
hành vi vốn hợp pháp bằng hồ sơ có sẵn); cờ ranh giới.

**Bốn họ kỹ thuật — viết ở lớp nhận diện:**

- **(a) Mô tả lại / đổi tên khoản chi.** Nhận diện: cùng một khoản được mô tả khác nhau tùy
  văn bản/lời khai/người hỏi — *chính sự không nhất quán là red flag*. Truy: so các phiên bản
  mô tả theo thời gian và người nhận; đối chiếu dòng tiền và hóa đơn gốc với tên gọi trên hồ
  sơ. Ranh giới: gọi đúng bản chất là hợp pháp; mô tả sai để qua kiểm tra có thể là bằng chứng
  chủ ý [cần đối chiếu]. *Không viết: danh sách mẫu câu thay thế.*
- **(b) Chia nhỏ/gom/chọn thời điểm quanh ngưỡng.** Nhận diện: chuỗi giá trị sát dưới ngưỡng,
  lặp lại, gần nhau. Truy: dựng dòng thời gian toàn bộ giao dịch, cộng gộp theo quan hệ lợi ích
  thay vì theo từng lần. Ranh giới: có sắp xếp hợp pháp; ranh giới nằm ở **chủ ý lách ngưỡng**
  và mối liên hệ với một quyết định — thẻ phải nêu cả hai phía để không hình sự hóa cái hợp
  pháp [cần đối chiếu]. *Không viết: số lần, mức chia, khoảng thời gian cụ thể.*
- **(c) Định giá thấp hơn giá trị thị trường.** Nhận diện: giá khai thấp hơn giá thị trường của
  cùng tài sản/bộ. Truy: định giá độc lập, đối chiếu nhà cung cấp và hóa đơn đầu vào. Ranh
  giới: vì sao không mức giá nào an toàn tuyệt đối — ngưỡng chỉ là một yếu tố [cần đối chiếu].
  *Không viết: mức giá cụ thể tuyên là "an toàn".*
- **(d) Xử lý chứng từ/tin nhắn sau khi có dấu hiệu bị kiểm tra.** Nhận diện: dấu hiệu tài liệu
  bị xóa/sửa/tạo muộn, liên lạc bị dọn. Truy: phục hồi dữ liệu, đối chiếu bản sao ở bên thứ ba,
  metadata. Ranh giới: **che giấu/tiêu hủy chứng cứ sau khi biết có kiểm tra thường là vi phạm
  riêng, nặng hơn hành vi gốc** [cần đối chiếu] — với phòng vệ đây là việc tuyệt đối không làm.
  *Không viết: thao tác cụ thể để xóa/sửa/che.*

**Ma trận yếu tố → bằng chứng (để lấp "thấy mà không chứng minh được").** Với mỗi họ kỹ thuật,
dựng bảng: *yếu tố cấu thành cần chứng minh → bằng chứng nào chứng minh nó → ai giữ → lấy bằng
công cụ pháp lý nào → chứng minh chủ ý bằng chuỗi hành vi gì*. Đây là thứ biến "tôi biết nó
làm" thành "tôi chứng minh được", và là công cụ trực tiếp cho bên hành pháp.

**Để lấp "chỉ phạt không ngăn được":** tách phần "vì sao tồn tại" thành đầu vào cho việc sửa
luật/bịt ngưỡng (ngăn tận gốc), cộng thiết kế điểm kiểm soát tại nơi ra quyết định, cộng chỉ số
cho thấy khi phát hiện thành thường quy thì kỹ thuật hết hiệu lực.

**Red-team hệ thống phát hiện (dùng nội bộ, không nằm trong thẻ tư vấn giao thân chủ):** mô
hình hóa nước đi của đối tượng ("sẽ đổi tên / chia nhỏ / định giá thấp / dọn chứng từ") ở mức
đủ để kiểm tra bộ phát hiện có bắt được không, rồi vá chỗ hở. Đây là việc *vá phát hiện*, không
phải viết how-to tối ưu.

---

## 7C. Thu thập dữ liệu tư vấn pháp luật

> Dữ liệu tư vấn phục vụ ba việc: sinh thẻ mẫu rủi ro, mở rộng golden set và bộ câu hỏi lại của
> Intake, tìm chủ đề hỏi nhiều mà kho văn bản đang yếu. **Không bao giờ là căn cứ pháp lý** —
> căn cứ chỉ đến từ kho văn bản qua `resolve()`.

### 7C.1 Nguyên tắc

Phân hạng nguồn trước rồi mới quyết định dùng vào việc gì. Che PII trước mọi bước có LLM ngoài
(mục 4). Lời kể chỉ cho biết mẫu hành vi; số liệu, ngày, số điều trong lời kể không dùng làm sự
kiện.

### 7C.2 Các loại nguồn

| Nguồn | Độ tin cậy | Dùng cho | Không dùng cho | Mức dữ liệu |
| --- | --- | --- | --- | --- |
| Văn bản, án lệ, bản án công khai | Cao | Vào kho theo mục 6, 7 | Không đi qua luồng 7C | C |
| Công văn, hỏi đáp của cơ quan nhà nước | Cao hơn ý kiến, vẫn đối chiếu bản gốc | Tìm cách hiểu, gợi ý `legal_link` | Thay văn bản gốc | C |
| Phiên tòa phát trực tiếp | Cao hơn, đối chiếu bản án | Tìm đầu mối, tìm bản án thật | Trích lời làm sự kiện | C (kiểm PII người ngoài cuộc) |
| Luật sư bình luận | Trung bình, là ý kiến | Gợi ý mẫu và cách lập luận | Làm căn cứ | C |
| Người dân kể, hỏi đáp diễn đàn | Thấp, một phía | Phát hiện mẫu câu hỏi và hành vi | Làm sự kiện | C sau khi che |
| Log tư vấn của chính Legal Agentic | Cao về thực tế, nhạy về bí mật | Golden set, ca bẫy, huấn luyện bộ chấm rủi ro | Gửi ra ngoài | A, chỉ nội bộ |

### 7C.3 Điều kiện trước khi thu

Có cơ sở hợp pháp, ghi lại (nguồn, người nói, ngày, loại nội dung, điều khoản áp dụng); luật sư
xem điều khoản nền tảng, bản quyền và NĐ 356/2025 trước khi thu hàng loạt, thử 20–30 mục từ
nguồn có phép trước; không thu từ nhóm kín, nội dung riêng tư, nội dung có trẻ em; với log của
chính khách cần sự đồng ý rõ ràng về việc dùng dữ liệu đã che để cải thiện hệ thống, có thời
hạn lưu và quyền rút lại; ghi mục đích sử dụng vào hồ sơ đánh giá tác động (mục 4).

### 7C.4 Luồng nạp

Ghi nguồn → ASR/OCR tự host (số liệu độ chắc thấp) → che PII trước mọi LLM ngoài → trích xuất
(mô hình rẻ; lớp tối ưu thực thi chuyển hóa thành chữ ký nhận diện, ghi log) → gom mẫu (≥ 2
nguồn độc lập) → đối chiếu `resolve(event_date, advice_date)` theo ngày sự kiện trong lời kể,
không theo ngày đăng → Verifier và bộ lọc ranh giới (7B.8) → luật sư duyệt.

**Bản ghi nguồn** (mỗi mục): source_id và loại nguồn; giấy phép/điều khoản/ngày thu; người
nói/vai trò; hash nội dung/mốc thời gian; trạng thái PII; ngày sự kiện được kể và độ chắc; độ
tin cậy/số nguồn độc lập; trạng thái (chờ duyệt, đã duyệt, bị loại kèm lý do).

### 7C.5 Dữ liệu tư vấn của chính Legal Agentic

Nguồn giá trị nhất và nhạy nhất. Chỉ dùng bản đã che, lưu nội bộ, không gửi nhà cung cấp ngoài
để huấn luyện. Ca bị luật sư sửa nhiều hoặc từ chối (9.3) là nguồn chính sinh ca golden set
mới, sau khi che. Hồ sơ gốc của khách ở mức A, không đi vào luồng gom mẫu. Xóa/ẩn danh theo
thời hạn lưu đã công bố.

### 7C.6 Rút gì và không rút gì

Rút: loại tình huống, câu hỏi thực tế và cách diễn đạt, sai lầm phổ biến, lập luận của luật sư,
kết quả và hậu quả được kể, dấu hiệu nhận biết, dấu vết, cách bên kiểm tra phát hiện, chiến
lược chứng cứ và phòng vệ hợp pháp. Không rút vào thẻ: lớp tối ưu thực thi (7B.2) — bước trích
xuất chuyển hóa thành chữ ký nhận diện, ghi log, chỉ giữ phần nhận diện, dấu vết và hậu quả.

### 7C.7 Chỉ số

| Chỉ số | Ngưỡng đề xuất |
| --- | --- |
| Mục dữ liệu có cơ sở hợp pháp ghi đủ | 100% |
| PII lọt qua trước LLM ngoài | 0 (cổng cứng) |
| Mẫu chính thức có ≥ 2 nguồn độc lập | 100% |
| Căn cứ đúng phiên bản theo ngày sự kiện | 100% |
| Lớp tối ưu thực thi lọt qua trích xuất | 0 (cổng cứng) |
| Ca golden set sinh từ log thật | Theo dõi |

### 7C.8 Rủi ro và việc cần xác minh

Thiên lệch nguồn (livestream/diễn đàn thiên về ca gây chú ý — dùng để tìm mẫu, không ước lượng
tần suất); tái định danh (coi như dữ liệu cá nhân, mức B); lời kể lỗi thời (bắt buộc qua
`resolve()`). Cần xác minh: điều khoản nền tảng, bản quyền, NĐ 356/2025, đồng ý của khách khi
dùng log, quy tắc hành nghề về dùng dữ liệu tư vấn.

**Vị trí trong lộ trình:** 7B/7C chạy cùng giai đoạn 4 (thẻ án lệ), sau khi `resolve()` và bộ
lọc ranh giới đã chạy — nhưng ở mức tự chủ 0 và chỉ khi có luật sư chuyên môn hình sự.

---

## 8. Intake, bảng sự kiện và máy tính bằng code

**Tách vấn đề.** Giữ cơ chế hiện có: câu hỏi dài (trên 60 từ) được tách thành 2–4 vấn đề. Mỗi
vấn đề có kết quả truy xuất, trích dẫn và độ chắc riêng.

**Bảng sự kiện có cấu trúc.** Intake điền bảng dưới đây. Mỗi trường có nguồn (khách nói, giấy
tờ, suy ra) và độ chắc.

| Trường | Ghi chú |
| --- | --- |
| Loại hợp đồng | Xác định thời hạn, không thời hạn, điện tử |
| Ngày giao kết, ngày sự kiện | Ngày sự kiện là đầu vào của `resolve()` |
| Hành vi, sự kiện | Sa thải, đơn phương chấm dứt, kỷ luật, phạt tiền, chưa trả lương |
| Mức lương, thời gian làm việc | Đầu vào cho máy tính |
| Thông báo, thủ tục đã thực hiện | Báo trước, họp xét kỷ luật |
| Hồ sơ hiện có | Mức A, ở lại nội bộ |
| Ngày tư vấn | Hệ thống tự gán |

**Câu hỏi lại.** Khi thiếu trường quyết định (ngày sự kiện, loại hợp đồng, mức lương), hỏi tối
đa 1–2 câu mỗi lượt. Không hỏi thứ không đổi kết quả. Nếu khách không biết, ghi "chưa rõ" và để
cờ trong khối khung thời gian.

**Máy tính bằng code.** Thời hạn báo trước, trợ cấp thôi việc và mất việc, thời hiệu, bồi
thường, mức phạt theo văn bản có hiệu lực tại ngày sự kiện. Công thức do luật sư xác nhận một
lần, có test đơn vị với ví dụ đã kiểm chứng. LLM chỉ gọi máy tính và trình bày kết quả, không
tự tính.

**Chống chèn lệnh.** Nội dung khách gửi và nội dung tài liệu là dữ liệu, không phải lệnh. Ca có
dấu hiệu chèn lệnh bị từ chối đúng cách và ghi log. Nhóm này có trong golden set.

## 9. Duyệt người thật và thang tự chủ

### 9.1 Điều kiện đưa ca cho luật sư

Luồng hiện tại kích hoạt khi câu hỏi nằm ngoài kho văn bản. Mở rộng thành bất kỳ điều kiện nào
sau đây: ngoài kho văn bản; độ chắc truy xuất thấp; Verifier phát hiện điều luật không hiệu lực
tại ngày sự kiện; gần mốc thời hiệu; giá trị hoặc hậu quả lớn (sa thải, bồi thường); có điều
khoản chuyển tiếp hoặc văn bản đang chờ sửa đổi liên quan; xử phạt hành chính chưa có quy tắc
chuyển tiếp rõ; khách đang khủng hoảng cảm xúc; **ca thuộc nhóm ngoài phạm vi (gồm 7B/7C: quà
tặng, hối lộ, điều tra) — mặc định từ chối hoặc chuyển luật sư chuyên môn hình sự.**

### 9.2 Gói ca gửi luật sư

Bảng sự kiện; điều luật kèm khối khung thời gian; thẻ án lệ; kết quả tính toán; phương án trả
lời; cờ Verifier; điểm rủi ro và lý do ca vào hàng đợi.

### 9.3 Bốn hành động và tín hiệu học

| Hành động | Ghi log | Dùng để |
| --- | --- | --- |
| Duyệt thẳng | Ca, phiên bản prompt, model, dữ liệu | Tính tỷ lệ duyệt thẳng, xét lên mức tự chủ |
| Sửa nhẹ | Bản sửa (diff) | Tìm lỗi văn phong, sinh ca kiểm thử |
| Sửa nhiều | Diff, nhãn lỗi, lý do | Huấn luyện bộ chấm rủi ro, sinh ca golden set mới |
| Từ chối | Lý do, nhãn lỗi | Hạ mức tự chủ, điều tra nguyên nhân gốc |

Bản ghi gồm: `case_id`, loại ca, điểm rủi ro, phiên bản prompt, model, dữ liệu và văn bản luật,
hành động, diff, nhãn lỗi, thời gian duyệt. Lưu nội bộ, dữ liệu đã che.

### 9.4 Thang tự chủ theo từng loại ca

| Mức | AI làm | Luật sư làm | Áp dụng cho |
| --- | --- | --- | --- |
| 0 | Soạn gói hồ sơ | Duyệt từng ca | Ca mới, ca rủi ro cao, **mọi ca nhóm 7B/7C** |
| 1 | Gửi khách kèm nhãn "chưa xác nhận" | Duyệt sau, trong SLA | Ca rủi ro thấp đã có số liệu |
| 2 | Gửi khách | Chỉ kiểm mẫu ngẫu nhiên | Loại ca lặp lại, ổn định |
| 3 | Tự xử lý | Không | Tra cứu, tính toán thuần (hạng Vãng lai) |

**Quy tắc vận hành thang.**

- Loại ca lên mức khi các chỉ số (tỷ lệ duyệt thẳng, sửa nhiều, sai trích dẫn) đạt ngưỡng qua
  đủ số ca liên tiếp. Ngưỡng do luật sư đặt. Gợi ý thống kê: 60 ca liên tiếp không sai nghiêm
  trọng chỉ chứng minh tỷ lệ lỗi thật dưới khoảng 5% (quy tắc 3/n); muốn dưới khoảng 2% cần
  khoảng 150 ca.
- Một lỗi nghiêm trọng thì loại ca tụt mức tự động.
- Văn bản gửi cơ quan chức năng luôn ở mức 0.
- Luật sư nghỉ hoặc ốm thì hệ thống tự hạ về mức 0 và dừng gửi khách. Cần sẵn một luật sư dự
  phòng theo hợp đồng.
- Chống duyệt qua loa: chèn ca "bẫy" đã biết đáp án vào hàng đợi, đo xem luật sư và Verifier có
  bắt được lỗi không.

## 10. Luồng dữ liệu theo từng vai

Hệ thống có hai nhóm vai: vai người và vai agent. Mỗi vai có đầu vào, đầu ra và giới hạn dữ
liệu riêng. Sơ đồ tương ứng nằm ở Phụ lục A.

| Vai | Đầu vào | Việc làm | Đầu ra | Dữ liệu được thấy | Giới hạn |
| --- | --- | --- | --- | --- | --- |
| Khách hàng | Câu hỏi, hồ sơ | Gửi, trả lời câu hỏi lại, nhận tư vấn | Bản tư vấn kèm khung thời gian, nhãn "chưa xác nhận" nếu ở mức 1 | Chỉ dữ liệu của mình | Không thấy log nội bộ |
| Luật sư chính | Gói ca, hàng đợi | Bốn hành động, kiểm mẫu, đặt ngưỡng, duyệt nạp văn bản, mở khóa khẩn | Quyết định, log | Mức A (nội bộ) | Người ký và chịu trách nhiệm |
| Luật sư dự phòng | Như trên | Thay khi luật sư chính vắng | Như trên | Theo hợp đồng | Cùng quyền, có log |
| Kỹ thuật kiêm bảo vệ dữ liệu (bán thời gian) | Log gateway, hồ sơ đánh giá tác động | Duyệt danh sách nhà cung cấp, cập nhật hồ sơ 6 tháng một lần, xử lý sự cố hạ tầng và bảo mật | Danh sách nhà cung cấp, hồ sơ | Cấu hình, metadata | Người được chỉ định về bảo vệ dữ liệu |
| Agent Data science | Log đã che, kết quả duyệt | Tìm chủ đề hỏi nhiều mà hệ thống yếu, huấn luyện classifier chấm rủi ro, dự báo chi phí và thời hiệu | Báo cáo, mô hình ứng viên | Chỉ dữ liệu đã che | Không ghi vào production |
| Agent AI developer | Trace lỗi, ca bị sửa nhiều | Đề xuất sửa prompt hoặc truy xuất, sinh ca kiểm thử | Pull request vào staging | Trace đã che | Chỉ ghi vào nhánh staging |
| Agent MLOps | Golden set, bản ứng viên | Chạy lại eval, huấn luyện lại reranker và classifier, triển khai thử một phần traffic, theo dõi drift | Kết quả cổng eval, phát hành | Chỉ số, bản mô hình | Tự phát hành khi vượt cổng eval |
| Agent LLMOps | Chi phí, trace, cảnh báo guardrail | Quản lý phiên bản prompt, định tuyến mô hình theo chi phí, giám sát PII, injection, credential | Cấu hình router, cảnh báo | Metadata | Cảnh báo lặp lại thì tự hạ mức tự chủ |
| Agent theo dõi công báo | Công báo hằng ngày | Phát hiện văn bản mới, soạn bản nạp để luật sư duyệt | Đề xuất nạp | Dữ liệu công khai (mức C) | Không tự nạp |

**Ranh giới quyết định.** Thay đổi liên quan nội dung pháp lý, như nạp văn bản luật mới hay sửa
mẫu hợp đồng, vẫn cần luật sư duyệt. Thay đổi thuần kỹ thuật thì cổng eval tự quyết. "Không cần
dev" chỉ đúng cho vận hành thường ngày. Sự cố hạ tầng và bảo mật vẫn cần một người kỹ thuật
hoặc dịch vụ thuê ngoài, dù chỉ bán thời gian.

## 11. Đo lường và cổng eval

### 11.1 Golden set năm nhóm

Luật sư gán đáp án. Mỗi ca có: bảng sự kiện, ngày sự kiện, ngày tư vấn, điều luật đúng kèm
phiên bản, và hành động mong đợi (trả lời, từ chối hay chuyển luật sư).

| Nhóm | Mục đích | Số ca khởi điểm (đề xuất) |
| --- | --- | --- |
| 1. Hỏi đáp thường | Đo truy xuất và trích dẫn trên câu hỏi đơn | 30 |
| 2. Nhiều vấn đề trong một câu | Đo bước tách vấn đề và trả lời đủ vấn đề | 20 |
| 3. Từ chối đúng | Ngoài phạm vi, chèn lệnh, **yêu cầu lớp tối ưu thực thi (7B)** | 20 (+15–20 cho 7B) |
| 4. Cần chuyển luật sư | Đo bộ điều kiện kích hoạt duyệt người thật | 20 |
| 5. Bẫy thời gian | Đo resolver, chuyển tiếp, hiệu lực dây chuyền | 30 |

Mở rộng lên trên 150 ca khi có dữ liệu duyệt thật, dùng ca bị sửa nhiều làm nguồn bổ sung.

**Nhóm bẫy thời gian** dựng ngay được từ các mốc đã kiểm chứng: sự kiện trước và sau 1/1/2021
(BLLĐ 2012 sang 2019); trước và sau 10/9/2026 (NĐ 12/2022 sang NĐ 283/2026); hợp đồng điện tử
trước và sau 1/1/2026; trợ cấp thất nghiệp quanh 1/1/2026; câu hỏi về luật còn ở dạng dự thảo
(trả vào mục "sắp thay đổi"); hợp đồng đang thực hiện dở qua mốc đổi luật; văn bản hướng dẫn
mất căn cứ vì văn bản gốc bị thay (hiệu lực dây chuyền).

### 11.2 Bảng chỉ số

Ngưỡng dưới đây là điểm khởi đầu đề xuất. Luật sư chốt ngưỡng cuối cùng sau khi có số liệu
baseline của v0.

| Chỉ số | Định nghĩa | Cách đo | Ngưỡng khởi điểm đề xuất |
| --- | --- | --- | --- |
| recall@k | Tỷ lệ ca mà điều luật đúng nằm trong top-k | Golden set | recall@5 ≥ 90% |
| Citation accuracy | Điều luật tồn tại, đoạn trích khớp nguyên văn | Code, kiểm 100% trích dẫn | 100% (cổng cứng) |
| Groundedness | Mọi nhận định nằm trong nguồn đã truy xuất | Verifier cộng luật sư kiểm mẫu | ≥ 95% |
| Đúng phiên bản theo ngày | Điều luật viện dẫn đúng phiên bản tại ngày sự kiện | Nhóm bẫy thời gian | 100%, mọi lỗi chặn phát hành |
| Tỷ lệ từ chối đúng | Từ chối đúng ca ngoài phạm vi, chèn lệnh | Nhóm 3 | ≥ 98%; chèn lệnh đã biết 100% |
| Lọt lớp tối ưu thực thi (7B) | Bộ ca đối kháng | 0 (cổng cứng) |
| Escalation recall | Ca cần luật sư mà hệ thống chuyển đúng | Nhóm 4 | ≥ 95% |
| Tỷ lệ sai nghiêm trọng | Kết luận sai gây hậu quả | Luật sư gán nhãn | 0 trong cửa sổ N ca liên tiếp để được lên mức |
| Tỷ lệ duyệt thẳng, sửa nhẹ, sửa nhiều, từ chối | Phân bố bốn hành động theo loại ca | Log bàn duyệt | Luật sư đặt theo từng loại ca |
| Thời gian duyệt mỗi ca | Từ lúc vào hàng đợi đến khi có quyết định | Log bàn duyệt | Theo SLA do luật sư đặt |
| Chi phí mỗi ca và tỷ lệ leo thang | Chi phí theo từng tầng, tỷ lệ ca phải lên tầng cao | Langfuse, LLMOps | Theo dõi xu hướng, đặt ngưỡng sau khi có số liệu |
| PII rò rỉ ra ngoài | Số lần PII thật hoặc giả lọt qua gateway | Bộ ca kiểm thử có PII giả | 0 (cổng cứng) |
| Độ tươi kho văn bản | Độ trễ từ ngày đăng công báo đến ngày nạp | Log nạp | Trong ngưỡng cờ "có thể chưa cập nhật" (đề xuất 30 ngày) |
| Tỷ lệ bắt ca bẫy | Tỷ lệ ca bẫy mà luật sư hoặc Verifier phát hiện | Ca bẫy chèn vào hàng đợi | Theo dõi, hạ mức tự chủ khi giảm |

### 11.3 Cỡ mẫu và ngưỡng tin cậy

Quy tắc 3/n: nếu 0 ca sai trên n ca thì cận trên của tỷ lệ lỗi thật xấp xỉ 3/n ở độ tin cậy 95%.

| Số ca, 0 sai | Cận trên tỷ lệ lỗi thật |
| --- | --- |
| 18 (hiện tại) | khoảng 17% |
| 60 | khoảng 5% |
| 150 | khoảng 2% |

Chỉ số đo trên golden set phải báo kèm số ca. Một con số "100%" trên 18 ca không được dùng để
nâng mức tự chủ.

### 11.4 Cổng eval

Mỗi thay đổi prompt, mô hình hoặc dữ liệu phải qua cổng mới được vào nhánh chính. **Cổng cứng**
(không đạt là chặn): citation accuracy, đúng phiên bản theo ngày, PII rò rỉ, chèn lệnh, lọt lớp
tối ưu thực thi (7B). **Cổng mềm**: các chỉ số còn lại không được tụt quá biên cho phép so với
baseline, biên do luật sư đặt. Chạy lại golden set mỗi khi nạp luật mới. Langfuse (đã có) làm
nền theo dõi trace và điểm số.

## 12. Lộ trình triển khai

Thứ tự dựa trên một ý: Data Gateway và golden set cùng cổng eval phải đứng trước, vì thiếu cổng
eval thì thang tự chủ và vòng vận hành tự động không có cơ sở để chạy. Phiên bản v0 còn nhỏ nên
mỗi giai đoạn được thiết kế để một người làm xong và kiểm chứng được trước khi sang bước tiếp.

| Giai đoạn | Nội dung | Điều kiện hoàn thành |
| --- | --- | --- |
| 0. Bảo mật (ngay) | Thu hồi khóa, nạp khóa lúc chạy, gitleaks trên toàn lịch sử (gồm `sync2.bundle`), quét bí mật trong CI | Không còn bí mật trong image và lịch sử |
| 1. Data Gateway, golden set, cổng eval | Phân loại A/B/C, che PII trước router, danh sách nhà cung cấp theo lớp, thay đua song song bằng leo thang; golden set năm nhóm; cổng eval trên Langfuse | PII rò rỉ = 0 trên bộ kiểm thử; golden set chạy tự động; có baseline của v0 |
| 2. Mô hình thời gian và nạp văn bản | Ba bảng, `resolve()`, khối khung thời gian; nạp NĐ 12/2022, NĐ 283/2026, NĐ 337/2025, Luật Việc làm 2013 và 2025 | Nhóm bẫy thời gian đúng phiên bản 100% |
| 3. Bàn duyệt luật sư và log | Gói ca, bốn hành động, điều kiện kích hoạt theo rủi ro, ca bẫy; mọi loại ca ở mức 0 | Mọi ca rủi ro vào hàng đợi; log đủ trường |
| 4. Intake, máy tính, thẻ án lệ, (7B/7C nếu có luật sư hình sự) | Bảng sự kiện, câu hỏi lại, máy tính; thẻ cho án lệ chính thức; tầng bản án thường có cờ; thẻ 7B.12 và luồng 7C ở mức tự chủ 0 | Máy tính qua test đơn vị do luật sư xác nhận; thẻ qua kiểm mẫu; bộ lọc ranh giới 7B.8 đạt cổng cứng |
| 5. Thang tự chủ và agent vận hành | Mức 1–3 cho loại ca đủ số liệu; agent Data science, AI developer, MLOps, LLMOps, theo dõi công báo | Loại ca đầu tiên lên mức 1 theo ngưỡng; tụt mức tự động hoạt động đúng |

## 13. Thay thế nhân sự đến đâu

| Vai | Mức thay thế khả thi | Phần còn lại |
| --- | --- | --- |
| Tiếp nhận, CSKH, lịch, báo tiến độ, hành chính | Gần hoàn toàn | Ca khách đang khủng hoảng cảm xúc chuyển sang người |
| Nghiên cứu pháp lý (paralegal) | Phần lớn | Verifier và mẫu kiểm ngẫu nhiên |
| Soạn thảo, rà soát hợp đồng (luật sư trẻ) | Phần lớn với mẫu chuẩn và hợp đồng lặp | Luật sư duyệt |
| Chiến lược, vấn đề pháp lý mới, thương lượng | Một phần: AI đưa phương án và tính toán | Phán đoán cuối là của người |
| Đại diện, tố tụng, ký, chịu trách nhiệm | Không | Luật sư |
| Bảo vệ dữ liệu cá nhân, tuân thủ | Phần lớn việc giám sát | Cần một người được chỉ định (theo nguồn đã tra, NĐ 356 có điều kiện đối với nhân sự bảo vệ dữ liệu) |
| Data, dev, MLOps, LLMOps | Phần lớn vận hành thường ngày | Sự cố hạ tầng và bảo mật |

**Bốn trần cứng mà công nghệ không gỡ được:**

1. Đại diện và ký: trước tòa và cơ quan chức năng, luật sư là người ký và đại diện.
2. Trách nhiệm nghề nghiệp: người chịu trách nhiệm khi tư vấn sai vẫn là luật sư.
3. Tuân thủ Luật AI: với hệ thống rủi ro trung bình và cao, nhà cung cấp phải tự phân loại và
   thông báo; hệ thống rủi ro cao phải qua đánh giá sự phù hợp trước khi vận hành. Việc này cần
   một người chịu trách nhiệm.
4. Lỗi còn lại của AI: chưa công cụ nào đạt 0%.

**Mức tối đa.** Có thể tham chiếu báo cáo Goldman Sachs năm 2023 ước tính 44% công việc pháp lý
có thể do AI làm, nhưng không nên chọn một con số rồi cam kết. Mức thay thế thật của từng loại
ca được đo trên golden set bằng tỷ lệ duyệt thẳng và tỷ lệ sai nghiêm trọng. Thang tự chủ ở mục
9 chính là cơ chế đẩy từng loại ca lên cao nhất có thể và hạ xuống ngay khi có lỗi.

**Cấu hình thực tế gần nhất với mục tiêu:** AI làm gần như toàn bộ lao động chuẩn bị, cộng một
luật sư chịu trách nhiệm, một người kỹ thuật kiêm bảo vệ dữ liệu bán thời gian, và một luật sư
dự phòng theo hợp đồng.

## 14. Pháp lý cần đối chiếu và rủi ro mở

Tác giả tài liệu không phải luật sư. Nhiều văn bản dưới đây lấy từ nguồn đã tra ở các lượt
trước, cần đối chiếu bản gốc trước khi dựa vào.

**Việc cần xác nhận:**

- **Luật Trí tuệ nhân tạo 134/2025/QH15**, hiệu lực từ 1/3/2026: chia hệ thống AI thành ba mức
  rủi ro, bắt buộc đánh giá sự phù hợp với hệ thống rủi ro cao trước khi vận hành.
- **Quyết định 33/2026/QĐ-TTg**, hiệu lực từ 15/8/2026: lập danh mục hệ thống AI rủi ro cao.
  Kiểm tra xem hệ thống tư vấn pháp lý có thuộc danh mục không. Điểm quyết định mức nghĩa vụ.
- **Nhãn "chưa xác nhận"**: khớp hướng minh bạch của luật về nội dung do AI tạo ra. Rà lại cách
  ghi nhãn theo văn bản hướng dẫn.
- **NĐ 356/2025 và NĐ 330**: dữ liệu cá nhân, hồ sơ đánh giá tác động chuyển dữ liệu xuyên biên
  giới, chế tài, điều kiện đối với nhân sự bảo vệ dữ liệu.
- **Hành nghề luật sư**: chưa kiểm chứng. Cần xác nhận mô hình "AI soạn, luật sư duyệt và chịu
  trách nhiệm" khớp quy định về hành nghề, **và quy tắc khi thân chủ muốn làm trái pháp luật**
  (liên quan trực tiếp 7B.10 Rủi ro 3).
- **Luật sửa đổi BLLĐ năm 2026**: xác minh đã được thông qua chưa, số hiệu và ngày hiệu lực.
- **Điều khoản sử dụng** của bộ 150 bản án và của từng nhà cung cấp LLM (nhất là gói miễn phí).
- **Nhóm 7B/7C:** văn bản về giá trị quà tặng và ngưỡng; đưa/nhận/môi giới/che giấu; bảo vệ
  người tố cáo; thu thập và sử dụng chứng cứ hợp pháp.

**Rủi ro mở và cách giảm thiểu:**

| Rủi ro | Giảm thiểu |
| --- | --- |
| Lỗi pháp lý còn lại | Verifier, luật sư duyệt, thang tự chủ có tụt mức |
| Luật sư là điểm lỗi đơn | Luật sư dự phòng; hệ thống tự hạ về mức 0 khi vắng |
| Duyệt qua loa | Ca bẫy đã biết đáp án trong hàng đợi |
| Tái định danh từ dữ liệu đã che | Coi mức B là dữ liệu cá nhân, giới hạn nhà cung cấp |
| Nguồn luật trễ cập nhật | Cờ "có thể chưa cập nhật", theo dõi công báo hằng ngày |
| Mô hình tự host kém hơn cho mức A | Luật sư duyệt kỹ hơn, chưa cho tự chủ cao |
| Tỷ lệ lỗi trên luật Việt Nam chưa đo | Đo bằng golden set trước khi nâng mức |
| Nội dung 7B bị đọc ngược thành hướng dẫn thực thi | Bộ lọc ranh giới 7B.8 (cổng cứng), luật sư hình sự duyệt từng thẻ, mức tự chủ 0 |

## 15. Đề xuất chốt cho các thành phần còn treo

Mục này gom mọi chỗ v1.0 để ngỏ và đề xuất một giá trị/hướng cụ thể để luật sư hoặc kỹ thuật
phê duyệt. **Đây là đề xuất kỹ thuật/vận hành, không phải căn cứ pháp lý.** Các chỗ pháp lý vẫn
ghi "cần đối chiếu" và chờ `resolve()` + luật sư.

### 15.1 Ngưỡng thang tự chủ (mục 9.4)

| Loại ca | Lên mức 1 khi | Lên mức 2 khi | Tụt về 0 khi |
| --- | --- | --- | --- |
| Tra cứu/tính toán thuần | 60 ca liên tiếp 0 sai nghiêm trọng, sửa nhiều ≤ 10% | thêm 150 ca, sửa nhiều ≤ 5% | bất kỳ 1 lỗi nghiêm trọng |
| Hỏi đáp lao động đơn | 60 ca, 0 sai nghiêm trọng, duyệt thẳng ≥ 80% | 150 ca, duyệt thẳng ≥ 90% | 1 lỗi nghiêm trọng, hoặc sửa nhiều > 15% trong 20 ca gần nhất |
| Soạn thảo mẫu chuẩn | 150 ca, duyệt thẳng ≥ 85% | không đề xuất lên mức 2 giai đoạn đầu | như trên |
| Nhóm 7B/7C | không lên mức nào | — | mặc định mức 0 |

Đề xuất: "lỗi nghiêm trọng" = kết luận pháp lý sai gây thiệt hại, hoặc viện dẫn điều luật sai
phiên bản lọt ra khách. Luật sư chốt định nghĩa.

### 15.2 Danh sách nhà cung cấp theo lớp dữ liệu (mục 4)

Không chốt tên nhà cung cấp ở đây (phụ thuộc điều khoản dữ liệu và vị trí máy chủ — cần đối
chiếu NĐ 356). Đề xuất **tiêu chí chọn**:

- Lớp A: chỉ mô hình tự host; nếu chưa đủ sức → từ chối/chuyển luật sư. Đề xuất ưu tiên một mô
  hình mở chạy nội bộ, chọn theo điểm trên golden set mức A.
- Lớp B: chỉ nhà cung cấp có (1) cam kết không dùng dữ liệu để huấn luyện, (2) máy chủ ở vùng
  pháp lý chấp nhận được hoặc có hồ sơ chuyển dữ liệu xuyên biên giới hợp lệ, (3) một dòng
  trong hồ sơ đánh giá tác động. Mỗi nhà cung cấp một mục, kỹ thuật kiêm bảo vệ dữ liệu duyệt.
- Lớp C: mở, gồm tìm web; vẫn ghi log.

### 15.3 Bộ chấm rủi ro (mục 3, 9) — đặc trưng khởi điểm bằng quy tắc

Điểm rủi ro = tổng trọng số của: giá trị/hậu quả lớn (sa thải, bồi thường) +3; gần mốc thời
hiệu +3; có điều khoản chuyển tiếp hoặc văn bản đang sửa +2; độ chắc truy xuất thấp +2; Verifier
báo cờ +3 (bất kỳ cờ nào → vào hàng đợi); ngoài phạm vi/nhóm 7B +∞ (luôn hàng đợi); khách khủng
hoảng cảm xúc +∞. Ngưỡng vào hàng đợi đề xuất ≥ 3. Sau khi có log, thay quy tắc bằng classifier
huấn luyện từ ca "sửa nhiều/từ chối".

### 15.4 Ngưỡng độ chắc truy xuất (mục 9.1)

Đề xuất: điểm rerank của kết quả top-1 dưới ngưỡng T1, hoặc khoảng cách điểm top-1 và top-2 nhỏ
hơn T2 → coi là "độ chắc thấp". Đặt T1, T2 bằng cách quét trên golden set sao cho escalation
recall ≥ 95% mà tỷ lệ chuyển luật sư không quá cao. Giá trị cụ thể chốt sau khi có baseline v0.

### 15.5 SLA duyệt và cấu hình luật sư dự phòng (mục 9, 13)

Đề xuất SLA: mức 0 — ca thường trong 1 ngày làm việc, ca gần mốc thời hiệu trong 4 giờ; mức 1 —
duyệt hậu kiểm trong 2 ngày làm việc. Luật sư dự phòng: hợp đồng sẵn, kích hoạt tự động khi luật
sư chính không phản hồi trong SLA hoặc báo vắng; trong thời gian không có ai, hệ thống ở mức 0
và dừng gửi khách.

### 15.6 Tần suất và tỷ lệ ca bẫy (mục 9.4)

Đề xuất chèn ca bẫy đã biết đáp án với tỷ lệ 1/20 ca trong hàng đợi, trộn ngẫu nhiên, mỗi tháng
đổi bộ. Nếu tỷ lệ bắt ca bẫy của luật sư hoặc Verifier tụt dưới 90% thì hạ mức tự chủ của loại
ca liên quan và rà lại quy trình duyệt.

### 15.7 Biên cổng mềm (mục 11.4)

Đề xuất: không chỉ số cổng mềm nào được tụt quá 2 điểm phần trăm tuyệt đối so với baseline
trong một lần phát hành; tụt quá thì chặn và cần luật sư/kỹ thuật ký ngoại lệ có log.

### 15.8 Độ tươi kho văn bản (mục 5.3)

Đề xuất giữ 30 ngày cho cờ "có thể chưa cập nhật"; riêng lĩnh vực xử phạt hành chính (biến động
nhanh, hậu quả tiền) rút xuống 14 ngày. Agent theo dõi công báo chạy hằng ngày.

### 15.9 Các mục pháp lý còn treo (mục 14) — hướng xử lý, không phải đáp án

Mỗi mục ở 14 nên thành một phiếu xác minh có người phụ trách, hạn hoàn thành, và trạng thái
(chưa tra / đã tra chờ luật sư / đã chốt). Trước khi một văn bản hoặc một quy tắc pháp lý được
dùng làm căn cứ, phiếu của nó phải ở trạng thái "đã chốt". Đề xuất chặn ở cổng eval: một thẻ/
câu trả lời viện dẫn căn cứ có phiếu chưa "đã chốt" thì không phát hành.

### 15.10 Quyết định cần con người chốt (tóm tắt)

| Hạng mục | Người chốt | Phụ thuộc |
| --- | --- | --- |
| Định nghĩa "lỗi nghiêm trọng", ngưỡng thang tự chủ | Luật sư | baseline v0 |
| Danh sách nhà cung cấp theo lớp | Kỹ thuật kiêm bảo vệ dữ liệu + luật sư | NĐ 356, điều khoản nhà cung cấp |
| Có triển khai 7B/7C hay không, khi nào | Luật sư (cần chuyên môn hình sự) | phạm vi, QĐ 33/2026 |
| Mọi căn cứ pháp lý `[cần đối chiếu]` | Luật sư | `resolve()` + văn bản gốc |
| Ngưỡng chỉ số cổng mềm/cứng cuối cùng | Luật sư + kỹ thuật | baseline v0 |

---

## Phụ lục A. Sơ đồ luồng dữ liệu theo từng vai

Các sơ đồ: (1) kiến trúc tổng thể và ranh giới nội bộ với bên ngoài; (2) luồng một ca từ khách
đến luật sư; (3) luồng của luật sư và vòng học; (4) vòng vận hành của các agent kỹ thuật; (5)
luồng cập nhật luật.

- **A.1 Kiến trúc tổng thể.** Khách chỉ chạm vào Data Gateway. Chỉ LLM Router nói chuyện với
  vùng ngoài, và chỉ bằng dữ liệu mức B và C đã che. Dữ liệu mức A không rời vùng nội bộ.
- **A.2 Luồng một ca theo vai.** Khách gửi, hệ thống chuẩn bị, rồi bộ chấm rủi ro chọn giữa
  hàng đợi luật sư (ca rủi ro) và gửi thẳng cho khách (loại ca đã ở mức tự chủ 1–3).
- **A.3 Luồng của luật sư và vòng học.** Bốn hành động đều vào log đã che; từ log, thang tự
  chủ, bộ chấm rủi ro và golden set được cập nhật.
- **A.4 Vòng vận hành của bốn agent kỹ thuật.** Mỗi agent có giới hạn quyền riêng; thay đổi nội
  dung pháp lý luôn qua luật sư, thay đổi thuần kỹ thuật do cổng eval quyết.
- **A.5 Luồng cập nhật luật.** Văn bản mới qua luật sư và cổng eval trước khi vào nhánh chính;
  cờ dây chuyền gắn theo `legal_link`.

*(Các sơ đồ chi tiết dạng hình giữ nguyên từ bản gốc v1.0, Phụ lục A.)*
