/* Nội dung hướng dẫn và bảng tra cứu (Minh 20/11/2026). Sửa chữ ở đây, không cần đụng component.

Tour: mỗi bước chỉ vào một phần tử có thuộc tính data-tour="<target>". Bước có `waitFor` chỉ đi
tiếp khi người dùng làm đúng thao tác (component phát sự kiện `lawvn:<waitFor>`); bước không có
`waitFor` đi tiếp bằng nút "Tiếp". Nhóm vai trò: guest (khách, chưa đăng nhập), user, lawyer, admin. */

export type RoleGroup = "guest" | "user" | "lawyer" | "admin";

export type TourStep = {
  id: string;
  target: string;      // data-tour của phần tử cần chỉ
  title: string;
  body: string;
  waitFor?: string;    // tên sự kiện lawvn:* phải xảy ra mới đi tiếp
  page?: string;       // đường dẫn trang chứa phần tử (bước của admin ở /upload…)
};

export type HelpEntry = {
  id: string;
  roles: RoleGroup[];
  topic: string;       // nhóm trong bảng tra cứu
  q: string;           // câu hỏi / tên chức năng
  a: string;           // trả lời ngắn
  tourStep?: string;   // "Chỉ cho tôi": id bước tour
};

export function roleGroup(role: string): RoleGroup {
  if (role === "admin" || role === "dev") return "admin";
  if (role === "lawyer") return "lawyer";
  if (role === "user") return "user";
  return "guest";
}

const ASK: TourStep[] = [
  { id: "ask", target: "composer", title: "Đặt câu hỏi ở đây",
    body: "Gõ tình huống của bạn (ví dụ: “Công ty trả lương chậm 20 ngày thì sao?”) rồi nhấn Enter hoặc nút gửi.",
    waitFor: "asked" },
  { id: "citations", target: "citations", title: "Mỗi câu trả lời đều có căn cứ",
    body: "Bấm vào một trích dẫn để mở đúng điều luật được dùng. Hãy bấm thử một trích dẫn.",
    waitFor: "citation-opened" },
  { id: "badges", target: "citations", title: "Ý nghĩa các huy hiệu",
    body: "✔ có trong kho đã duyệt · ⏳ có trong kho, đang chờ luật sư duyệt · ✖ ngoài kho, cần kiểm lại. “Bản ghi sẵn” = câu trả lời đã chạy trước đó (máy chủ AI đang chậm)." },
];

const VOICE: TourStep[] = [
  { id: "mic", target: "mic", title: "Nói thay vì gõ",
    body: "Bấm micro cạnh nút Gửi: chữ chạy thẳng vào ô hỏi khi bạn nói (chữ xám là tạm, chốt câu thì thành chữ đen). Bấm lại để dừng, gõ tay đoạn tiếng Anh, rồi bấm để nói tiếp. Bấm thử ngay.",
    waitFor: "dictation-started" },
  { id: "send-mask", target: "composer", title: "Bấm Gửi mới làm mờ",
    body: "Khi bấm Gửi, nếu câu có tên người, công ty, số điện thoại hay tình tiết riêng tư, bạn được chọn làm mờ từng đoạn trước khi gửi. Không có gì nhạy cảm thì gửi thẳng." },
  { id: "mask", target: "voice-spans", title: "Bạn quyết định cái gì được gửi",
    body: "Mỗi đoạn chọn “Thay tên giả” (ví dụ Nguyễn Văn B) hoặc “Giữ nguyên” nếu cần để hiểu vụ việc.",
    waitFor: "mask-chosen" },
  { id: "drop", target: "attach", title: "Có sẵn tệp ghi âm?",
    body: "Bấm kẹp giấy hoặc kéo thả tệp ghi âm/video vào ô hỏi (như Google Drive). Bản chép lời đi qua cùng bước làm mờ và hai ô đồng ý trước khi lưu hồ sơ." },
];

const TOOLS: TourStep[] = [
  { id: "contract", target: "nav-contract", title: "Rà soát hợp đồng",
    body: "Dán hoặc tải hợp đồng lao động: hệ thống đối chiếu từng điều với Bộ luật Lao động 2019 và lương tối thiểu vùng tại ngày áp dụng, chỉ ra điểm trái luật kèm căn cứ. Chạy bằng luật lập trình sẵn, không gửi nội dung ra ngoài." },
  { id: "follow", target: "nav-follow", title: "Theo dõi luật mới",
    body: "Chọn lĩnh vực và từ khoá; văn bản mới quét được mà khớp sẽ hiện ở đây kèm lý do khớp." },
];

const LAWYER: TourStep[] = [
  { id: "dashboard", target: "nav-dashboard", title: "Hàng đợi của luật sư",
    body: "Câu hỏi khó hoặc rủi ro cao được chuyển tới đây kèm bằng chứng. Bạn trả lời, sửa hoặc từ chối kèm lý do; mỗi lần sửa được ghi lại để hệ thống học." },
  { id: "docgen", target: "nav-docgen", title: "Đề xuất và dùng mẫu văn bản",
    body: "Đề xuất mẫu mới cho admin chỉnh và khoá. Mẫu đã khoá thì điền theo từng vụ việc, kèm căn cứ và ngày áp dụng." },
];

export const TOURS: Record<RoleGroup, TourStep[]> = {
  guest: [...ASK, ...TOOLS, ...VOICE],
  lawyer: [...ASK, ...LAWYER, ...TOOLS, ...VOICE],
  user: [...ASK, ...TOOLS, ...VOICE,
    { id: "history", target: "sidebar", title: "Lịch sử hội thoại",
      body: "Các cuộc trò chuyện của bạn được lưu ở đây; bấm để mở lại, “Cuộc trò chuyện mới” để bắt đầu vụ khác." }],
  admin: [...ASK,
    { id: "upload", target: "nav-upload", title: "Nạp và duyệt văn bản",
      body: "Trang Tải lên: văn bản mới (Công báo, tài liệu nội bộ) nằm ở trạng thái chờ duyệt. Văn bản chỉ được dùng để trả lời sau khi bạn duyệt." },
    { id: "graph", target: "nav-graph", title: "Bản đồ điều luật",
      body: "Xem các điều luật dẫn chiếu nhau, kiểm văn bản thay thế và hiệu lực." },
    { id: "docgen-admin", target: "nav-docgen", title: "Chỉnh và khoá mẫu văn bản",
      body: "Mẫu luật sư đề xuất nằm ở trang Soạn thảo. Mỗi lần lưu là một phiên bản; khi khoá, hệ thống kiểm biến và căn cứ, bản đã khoá không sửa được." },
    ...TOOLS, ...VOICE],
};

export const HELP: HelpEntry[] = [
  { id: "h-ask", roles: ["guest", "user", "lawyer", "admin"], topic: "Hỏi đáp",
    q: "Hỏi một câu như thế nào?", a: "Gõ tình huống vào ô cuối trang, nêu thời điểm xảy ra nếu có (luật áp dụng theo ngày). Nhấn Enter để gửi.", tourStep: "ask" },
  { id: "h-cite", roles: ["guest", "user", "lawyer", "admin"], topic: "Hỏi đáp",
    q: "Trích dẫn [1], [2] là gì?", a: "Điều luật mà câu trả lời dựa vào. Bấm để đọc nguyên văn điều đó.", tourStep: "citations" },
  { id: "h-badge", roles: ["guest", "user", "lawyer", "admin"], topic: "Hỏi đáp",
    q: "✔ ⏳ ✖ nghĩa là gì?", a: "✔ có trong kho đã duyệt; ⏳ trong kho nhưng chờ luật sư duyệt; ✖ ngoài kho, cần kiểm lại trước khi dùng.", tourStep: "badges" },
  { id: "h-time", roles: ["guest", "user", "lawyer", "admin"], topic: "Hỏi đáp",
    q: "Vì sao câu trả lời hỏi ngày xảy ra sự việc?", a: "Luật thay đổi theo thời gian. Hệ thống chọn văn bản có hiệu lực tại ngày sự việc (ví dụ việc năm 2019 dùng Bộ luật Lao động 2012)." },
  { id: "h-prerec", roles: ["guest", "user", "lawyer", "admin"], topic: "Hỏi đáp",
    q: "“Bản ghi sẵn” là gì?", a: "Ở trang Demo, nếu máy chủ AI chậm quá 8 giây thì hiện câu trả lời thật đã chạy trước đó cho đúng câu hỏi mẫu." },
  { id: "h-mic", roles: ["guest", "user", "lawyer", "admin"], topic: "Ghi âm và làm mờ",
    q: "Nói thay vì gõ", a: "Bấm micro cạnh nút Gửi, chữ chạy vào ô. Bấm lại để dừng, gõ tay (ví dụ đoạn tiếng Anh), rồi bấm để nói tiếp; chữ chèn đúng chỗ con trỏ. Âm thanh chỉ gửi tới máy chủ Legal Agentic, không gửi Google.", tourStep: "mic" },
  { id: "h-drop", roles: ["guest", "user", "lawyer", "admin"], topic: "Ghi âm và làm mờ",
    q: "Kéo thả tệp ghi âm/video", a: "Bấm kẹp giấy cạnh ô hỏi hoặc kéo tệp vào ô. Nhận nhiều tệp một lúc; tệp dài trên 20 phút gửi qua mục Tải lên.", tourStep: "drop" },
  { id: "h-mask", roles: ["guest", "user", "lawyer", "admin"], topic: "Ghi âm và làm mờ",
    q: "Làm mờ tên người, công ty", a: "Khi bấm Gửi (hoặc sau khi chép tệp ghi âm), mỗi đoạn nhạy cảm được liệt kê. Chọn “Thay tên giả” hoặc “Giữ nguyên”; sửa được tên giả, cùng một người luôn cùng một tên giả.", tourStep: "mask" },
  { id: "h-keep", roles: ["guest", "user", "lawyer", "admin"], topic: "Ghi âm và làm mờ",
    q: "Giữ nguyên tình tiết nhạy cảm có an toàn không?", a: "Bản có đoạn giữ nguyên chỉ được xử lý trong máy chủ Legal Agentic, không gửi AI bên ngoài và không dùng làm dữ liệu huấn luyện." },
  { id: "h-consent", roles: ["guest", "user", "lawyer", "admin"], topic: "Ghi âm và làm mờ",
    q: "Hai ô đồng ý (tệp ghi âm)", a: "Với tệp ghi âm: (a) dùng bản đã làm mờ để lập hồ sơ; (b) góp bản đã làm mờ vào dữ liệu cải thiện. Không tick (a) thì không lưu gì. Bản gốc không bao giờ được lưu." },
  { id: "h-quota", roles: ["guest"], topic: "Tài khoản",
    q: "Vì sao bị giới hạn số câu hỏi?", a: "Khách chưa đăng nhập có số câu mỗi ngày giới hạn. Đăng nhập để có thêm lượt và lưu lịch sử." },
  { id: "h-history", roles: ["user", "lawyer", "admin"], topic: "Tài khoản",
    q: "Xem lại hội thoại cũ", a: "Thanh bên trái liệt kê các cuộc trò chuyện; bấm để mở lại.", tourStep: "history" },
  { id: "h-escalate", roles: ["user", "lawyer", "admin"], topic: "Hỏi đáp",
    q: "Câu hỏi ngoài phạm vi thì sao?", a: "Hệ thống từ chối trả lời bừa và đề nghị chuyển cho chuyên gia; bạn chọn gửi hay không." },
  { id: "h-upload", roles: ["admin"], topic: "Quản trị",
    q: "Nạp văn bản luật mới", a: "Trang Tải lên: tải tệp PDF/DOCX hoặc xem văn bản nạp tự động từ Công báo. Văn bản chờ duyệt cho tới khi bạn bấm duyệt.", tourStep: "upload" },
  { id: "h-approve", roles: ["admin"], topic: "Quản trị",
    q: "Duyệt văn bản và ngày hiệu lực", a: "Kiểm số hiệu, tên, ngày hiệu lực (đọc từ điều khoản thi hành) và quan hệ thay thế trước khi duyệt. Văn bản hiệu lực theo giai đoạn cần luật sư xem." },
  { id: "h-graph", roles: ["admin"], topic: "Quản trị",
    q: "Bản đồ điều luật", a: "Trang Graph hiển thị dẫn chiếu giữa các điều, văn bản thay thế và hiệu lực.", tourStep: "graph" },
  { id: "h-review", roles: ["lawyer", "admin"], topic: "Quản trị",
    q: "Hàng đợi chuyên gia", a: "Trang Dashboard: câu hỏi người dùng chuyển cho chuyên gia, trả lời hoặc từ chối kèm lý do." },
  { id: "h-contract", roles: ["guest", "user", "lawyer", "admin"], topic: "Công cụ",
    q: "Rà soát hợp đồng lao động", a: "Mục Rà soát hợp đồng: dán nội dung hoặc tải DOCX/PDF. Kết quả liệt kê điểm trái luật, cần sửa, lưu ý; mỗi điểm có điều luật căn cứ và đề xuất sửa.", tourStep: "contract" },
  { id: "h-follow", roles: ["guest", "user", "lawyer", "admin"], topic: "Công cụ",
    q: "Theo dõi văn bản mới theo lĩnh vực", a: "Mục Theo dõi luật mới: chọn lĩnh vực, thêm từ khoá. Số tin mới hiện cạnh từng đăng ký.", tourStep: "follow" },
  { id: "h-docgen", roles: ["lawyer", "admin"], topic: "Công cụ",
    q: "Soạn văn bản từ mẫu đã khoá", a: "Trang Soạn thảo: chọn mẫu đã khoá, điền từng trường (ngày, tiền, số được kiểm kiểu). Luật sư đề xuất mẫu mới; admin chỉnh và khoá.", tourStep: "docgen" },
  { id: "h-agents", roles: ["lawyer", "admin"], topic: "Công cụ",
    q: "Agent điều phối nhiều tầng là gì?", a: "Chế độ chat “agents”: bộ điều phối đọc câu bằng code rồi giao cho rà soát hợp đồng, tra cứu theo lĩnh vực, tính toán hoặc soạn thảo; sau đó kiểm trích dẫn và chấm rủi ro." },
  { id: "h-keys", roles: ["guest", "user", "lawyer", "admin"], topic: "Phím tắt",
    q: "Phím tắt", a: "Enter: gửi · Shift+Enter: xuống dòng · ?: mở bảng tra cứu · Esc: đóng cửa sổ." },
];
