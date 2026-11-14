# Bản sửa 7B/7C — Tách "công thức thực thi" khỏi "kỹ thuật lẩn tránh góc nhìn điều tra"

> Mục đích bản sửa: trả lời đúng nhu cầu của bên hành pháp và bên phòng vệ (phải hiểu kỹ
> thuật lẩn tránh để truy vết và đối đáp), mà không biến thẻ thành cẩm nang phạm tội.
> Thay cho cách diễn đạt cũ "không rút vào thẻ" — vốn gộp nhầm hai thứ khác nhau.

---

## 0. Nguyên tắc tách (đặt lên đầu 7B, thay cho ranh giới cũ ở 7B.2)

Một "dấu hiệu phía thực thi" gồm hai lớp **phải tách rời**:

- **Lớp nhận diện (đối kháng để điều tra):** kỹ thuật đó *là gì* ở mức đủ để nhận ra nó;
  nó để lại *dấu vết gì*; điều tra viên *đối chiếu bằng gì*; hậu quả pháp lý; và bên phòng
  vệ *phản biện hợp pháp* ra sao. → **Rút vào thẻ. Càng sâu càng tốt.**
- **Lớp tối ưu thực thi (công thức):** làm *thế nào cho trót lọt* — mẫu câu thay thế cụ
  thể, cách chia/gom/chọn thời điểm cụ thể để xuống dưới ngưỡng, mức giá được tuyên là "an
  toàn", thao tác xóa/sửa chứng từ. → **Không rút vào thẻ, ở mọi hạng khách.**

Phép thử một dòng cho từng câu chữ trong thẻ: *câu này giúp người đọc **nhận ra và chứng
minh** hành vi, hay giúp họ **thực hiện trót lọt** hành vi?* Nếu là vế sau, cắt.

Lý do lớp tối ưu bị cắt kể cả với khách VIP — chính là lập luận 7B.10 Rủi ro 1 của bản gốc:
một văn bản thực thi có cùng giá trị với bất kỳ ai cầm nó. Kiểm chứng đạo đức **người đọc**
không làm giảm giá trị của **văn bản** khi nó rời khỏi tay người đó. Trong khi đó, lớp nhận
diện không cần cổng nào, vì nó phục vụ phát hiện và phòng vệ, không phục vụ thực thi.

Điểm mấu chốt cho bên hành pháp: **điều tra viên không cần công thức tối ưu của tội phạm.**
Họ cần chữ ký, dấu vết và cách chứng minh. Lớp nhận diện cho họ nhiều hơn công thức cho họ.

---

## 7B.12 Thẻ kỹ thuật lẩn tránh — góc nhìn điều tra (MỚI)

Đây là nơi chứa đúng phần bạn lo mất. Mỗi kỹ thuật lẩn tránh được viết **từ phía điều tra
và phòng vệ**, không viết từ phía người thực hiện.

### Schema (mỗi kỹ thuật một thẻ)

| Trường | Nội dung |
| --- | --- |
| technique_id, tên | Tên trung tính, mô tả họ kỹ thuật (vd: "định giá thấp hơn giá trị thị trường") |
| mô tả nhận diện | Kỹ thuật là gì, ở mức đủ để nhận ra — KHÔNG ở mức công thức để làm |
| vì sao tồn tại | Khe hở pháp lý/định nghĩa (kèm `provision_key` nếu có) |
| chữ ký / red flags | Dấu hiệu định lượng và định tính để nghi ngờ |
| bản đồ dấu vết | Chứng cứ nào tồn tại, ai giữ, truy bằng gì (theo 7B.5a) |
| cách điều tra đối chiếu | Các nguồn và phép so khớp bên kiểm tra dùng |
| ranh giới pháp lý | Chỗ nào là hành vi hợp pháp, chỗ nào vượt sang vi phạm; yếu tố chủ ý |
| căn cứ (qua `resolve()`) | Điều luật đúng phiên bản theo ngày sự kiện — không điền từ trí nhớ |
| hậu quả theo vai | Người cho / nhận / trung gian / tư vấn |
| hướng điều tra (bên hành pháp) | Cần tìm gì, ở đâu, theo thứ tự nào; cách bảo toàn giá trị chứng cứ |
| phản biện hợp pháp (bên bị cáo buộc) | Cách chứng minh hành vi vốn hợp pháp bằng hồ sơ có sẵn |
| cờ ranh giới | Đánh dấu nếu câu chữ trượt sang lớp tối ưu thực thi → chặn |

### Bốn họ kỹ thuật — viết ở lớp nhận diện

Dưới đây là khung từng họ. Nội dung cụ thể để trống chỗ căn cứ cho tới khi `resolve()` đối
chiếu văn bản gốc; các chỗ "[cần đối chiếu]" cố ý không điền số điều từ trí nhớ.

**(a) Mô tả lại / đổi tên món quà, khoản chi**
- Nhận diện: cùng một khoản được mô tả khác nhau tùy văn bản, lời khai hoặc người hỏi.
- Chữ ký: *chính sự không nhất quán giữa các nguồn là red flag*; mô tả trong hồ sơ lệch với
  bản chất kinh tế; cách gọi thay đổi sau khi có dấu hiệu bị hỏi.
- Dấu vết & truy: so sánh các phiên bản mô tả theo thời gian và theo người nhận; đối chiếu
  dòng tiền và hóa đơn gốc với tên gọi trên hồ sơ; lời khai nhiều bên.
- Ranh giới pháp lý: gọi đúng bản chất là hợp pháp; mô tả sai bản chất để qua kiểm tra có
  thể bị coi là **bằng chứng của chủ ý**, thường nặng hơn bản thân khoản chi [cần đối chiếu].
- Hướng điều tra: khóa lại từng phiên bản mô tả kèm nguồn và ngày trước khi đối tượng kịp
  thống nhất lời khai.
- Phản biện hợp pháp: chứng minh tên gọi khớp bản chất kinh tế bằng chứng từ cùng thời điểm.

> KHÔNG viết: danh sách tên gọi/mẫu câu thay thế để mô tả lại cho "an toàn".

**(b) Chia nhỏ / gom / chọn thời điểm quanh ngưỡng (structuring)**
- Nhận diện: chuỗi giao dịch có giá trị nằm ngay dưới ngưỡng, lặp lại, gần nhau.
- Chữ ký: cụm giá trị sát ngưỡng một cách bất thường; tần suất và khoảng cách đều đặn; tổng
  gộp vượt xa ngưỡng dù từng lần dưới ngưỡng.
- Dấu vết & truy: dựng dòng thời gian toàn bộ giao dịch giữa các bên; cộng gộp theo quan hệ
  lợi ích thay vì theo từng lần; đối chiếu log phê duyệt.
- Ranh giới pháp lý: đây là chỗ cần cẩn trọng nhất — có những sắp xếp **hợp pháp** (vd kế
  hoạch chi tiêu, thời điểm thực tế của giao dịch). Ranh giới nằm ở **chủ ý lách ngưỡng** và
  mối liên hệ với một quyết định. Thẻ phải nêu rõ cả hai phía để không hình sự hóa cái hợp
  pháp [cần đối chiếu định nghĩa và ngưỡng].
- Hướng điều tra: chứng minh chủ ý bằng chuỗi hành vi, không bằng một giao dịch đơn lẻ.
- Phản biện hợp pháp: chứng minh mỗi giao dịch có lý do kinh tế độc lập, thời điểm là thực
  chất chứ không chọn để lách.

> KHÔNG viết: số lần, mức chia, khoảng thời gian cụ thể để giữ dưới ngưỡng.

**(c) Định giá thấp hơn giá trị thị trường (món quà "nhìn nhỏ")**
- Nhận diện: giá trị khai thấp hơn giá trị thị trường của cùng tài sản/bộ.
- Chữ ký: chênh lệch giữa giá khai và giá thị trường của cả bộ; dùng giá mua vào thay vì giá
  bán; mô tả nguồn gốc khác bản chất.
- Dấu vết & truy: định giá độc lập theo giá thị trường; đối chiếu nhà cung cấp và hóa đơn đầu
  vào; so với giao dịch tương đương.
- Ranh giới pháp lý: vì sao **không mức giá nào an toàn tuyệt đối** — ngưỡng chỉ là một yếu
  tố, chủ ý và quan hệ lợi ích vẫn quyết định [cần đối chiếu cách xác định giá trị và ngưỡng].
- Hướng điều tra: lập hồ sơ định giá độc lập trước khi đối tượng kịp đưa chứng từ giá thấp.
- Phản biện hợp pháp: chứng minh giá khai phản ánh đúng giá trị thực bằng định giá khách quan.

> KHÔNG viết: mức giá cụ thể được tuyên là "an toàn".

**(d) Xử lý chứng từ, tin nhắn, tài liệu sau khi có dấu hiệu bị kiểm tra**
- Nhận diện: dấu hiệu tài liệu bị xóa, sửa, tạo muộn, hoặc liên lạc bị dọn.
- Chữ ký: khoảng trống bất thường trong log; metadata chỉnh sửa; thời điểm tạo hồ sơ lệch với
  sự kiện; bản sao còn ở nơi khác mâu thuẫn với bản đã dọn.
- Dấu vết & truy: phục hồi dữ liệu; đối chiếu bản sao ở bên thứ ba (ngân hàng, nhà cung cấp,
  bên nhận); nhật ký hệ thống; metadata.
- Ranh giới pháp lý: **che giấu/tiêu hủy chứng cứ sau khi biết có kiểm tra thường là một vi
  phạm riêng và nặng hơn hành vi gốc** [cần đối chiếu]. Đây là điểm cả bên điều tra và bên
  phòng vệ đều phải nắm: với phòng vệ, đây là việc **tuyệt đối không làm**.
- Hướng điều tra: việc dọn dẹp tự nó để lại dấu vết và tự nó là đòn bẩy buộc tội.
- Phản biện hợp pháp: giữ nguyên hiện trạng, khắc phục minh bạch; không bao giờ dọn dấu vết.

> KHÔNG viết: thao tác cụ thể để xóa/sửa/che chứng từ, tin nhắn.

### Ranh giới "phòng vệ" vs "che giấu" (ghi thẳng vào thẻ)

Phòng vệ hợp pháp = chứng minh hành vi vốn hợp pháp + giữ hồ sơ minh bạch + khắc phục từ hiện
tại. Nó **không bao gồm** làm mỏng dấu vết của hành vi có vấn đề; việc đó là che giấu/cản trở.
Hệ thống của bên hành pháp không được tạo đầu ra thuộc nhóm thứ hai, kể cả khi đóng khung là
"giúp thân chủ phòng bị". "Hạn chế tìm được bằng chứng" đối với hành vi đã xảy ra nằm ở phía
che giấu, không phải phía phòng vệ.

---

## 7C — Quy tắc trích xuất khi nguồn chứa nội dung phía thực thi (sửa 7C.4 bước 4 và 7C.6)

Khi một nguồn (livestream, lời kể, bình luận) chứa cả công thức thực thi:

1. **Chuyển hóa, không sao chép.** Trích họ kỹ thuật thành **một chữ ký nhận diện + bản đồ
   dấu vết**, bỏ phần tham số tối ưu (mức chia, mẫu câu, mức giá, thao tác che).
2. **Ghi log** việc đã loại phần tối ưu (để kiểm thử bộ lọc, không giữ nội dung).
3. **Gắn vào thẻ 7B.12** ở lớp nhận diện, kèm `resolve()` cho căn cứ.
4. Verifier 7B.8 chặn nếu đầu ra còn tham số tối ưu; ca này vào golden set nhóm 3 (từ chối).

Nói cách khác: mọi thứ bên hành pháp học được từ nguồn về "cách người ta lách" được giữ lại
**dưới dạng cách nhận ra và truy**, không dưới dạng cách làm.

---

## Cập nhật chỉ số (bổ sung 7B.9 / 7C.7)

| Chỉ số | Ngưỡng |
| --- | --- |
| Thẻ 7B.12 có đủ: chữ ký, bản đồ dấu vết, cách đối chiếu, ranh giới pháp lý, căn cứ qua resolve | 100% |
| Thẻ 7B.12 lọt tham số tối ưu thực thi (mức chia/mẫu câu/giá "an toàn"/thao tác che) | 0 (cổng cứng) |
| Ca golden nhóm 3: yêu cầu công thức tối ưu bị từ chối, kèm đề nghị chuyển sang lớp nhận diện | theo dõi, luật sư đặt ngưỡng |
| Mỗi họ kỹ thuật nêu được cả hành vi hợp pháp lẫn vi phạm (chống hình sự hóa cái hợp pháp) | 100% với họ (b),(c) |

---

## Vì sao cách này trả lời đủ nhu cầu bạn nêu

- **Bên hành pháp / thu thập bằng chứng:** nhận đủ chữ ký, bản đồ dấu vết, hướng điều tra
  theo thứ tự, cách bảo toàn giá trị chứng cứ — nhiều hơn bản cũ. Đây mới là thứ dựng được hồ
  sơ; công thức tối ưu của đối tượng không dựng hồ sơ.
- **Bên có tính cạnh tranh / bị kéo vào:** nhận đủ chữ ký để nhận ra mình đang bị đặt vào
  thế, và đường thu thập/bảo toàn chứng cứ hợp pháp.
- **Bên bị cáo buộc:** nhận đủ ranh giới pháp lý và cách phản biện bằng hồ sơ thật, gồm cả
  cảnh báo rõ về việc che giấu làm hậu quả nặng thêm.
- Phần duy nhất không có — công thức để thực hiện trót lọt — không phục vụ ba nhu cầu trên.
