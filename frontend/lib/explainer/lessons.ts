/* Bài học tương tác "Hiểu hệ thống LawVN" (Minh 20/11/2026). Mỗi bài: các nút (ai/cái gì xử lý),
   các cạnh (dữ liệu đi đâu), các bước; mỗi bước chiếu sáng nút/cạnh đang chạy và ghi rõ
   đã có / đang làm / lộ trình. Sửa nội dung ở đây, trang tự vẽ. */

export type Status = "done" | "wip" | "roadmap";
export type Node = { id: string; label: string; sub: string; x: number; y: number; kind: "person" | "code" | "model" | "store" | "web" };
export type Edge = { from: string; to: string; label?: string };
export type Step = {
  title: string; body: string; status: Status;
  nodes: string[]; edges: [string, string][];
  problem?: string; metric?: { label: string; value: string }[];
};
export type Lesson = { id: string; title: string; minutes: number; summary: string; nodes: Node[]; edges: Edge[]; steps: Step[] };

export const STATUS_LABEL: Record<Status, string> = { done: "Đã có", wip: "Đang làm", roadmap: "Lộ trình" };

export const LESSONS: Lesson[] = [
  {
    id: "genai-van-ban", title: "GenAI soạn văn bản", minutes: 6,
    summary: "Từ đề xuất của luật sư tới template đã khoá, rồi hệ thống soạn văn bản cho khách: ai làm gì, ở đâu, kiểm bằng gì.",
    nodes: [
      { id: "lawyer", label: "Luật sư", sub: "đề xuất mẫu", x: 70, y: 70, kind: "person" },
      { id: "admin", label: "Admin", sub: "chỉnh, chốt", x: 70, y: 230, kind: "person" },
      { id: "editor", label: "Trình soạn", sub: "sửa trực tiếp", x: 260, y: 150, kind: "code" },
      { id: "tpl", label: "Thư viện mẫu", sub: "template khoá, có phiên bản", x: 450, y: 70, kind: "store" },
      { id: "kb", label: "Kho luật", sub: "điều khoản theo hiệu lực", x: 450, y: 230, kind: "store" },
      { id: "fill", label: "Điền biến", sub: "code", x: 640, y: 70, kind: "code" },
      { id: "model", label: "Model riêng", sub: "gợi ý câu chữ", x: 640, y: 230, kind: "model" },
      { id: "check", label: "Kiểm bằng code", sub: "thể thức, căn cứ, số hiệu", x: 830, y: 150, kind: "code" },
      { id: "client", label: "Khách / luật sư", sub: "nhận văn bản", x: 1010, y: 150, kind: "person" },
    ],
    edges: [
      { from: "lawyer", to: "admin", label: "đề xuất" }, { from: "admin", to: "editor" },
      { from: "editor", to: "tpl", label: "chốt" }, { from: "kb", to: "editor", label: "căn cứ" },
      { from: "tpl", to: "fill" }, { from: "fill", to: "model" }, { from: "kb", to: "model" },
      { from: "model", to: "check" }, { from: "fill", to: "check" }, { from: "check", to: "client" },
    ],
    steps: [
      { title: "Luật sư đề xuất mẫu", status: "roadmap", nodes: ["lawyer", "admin"], edges: [["lawyer", "admin"]],
        body: "Luật sư gửi một mẫu văn bản hay dùng (hợp đồng lao động, quyết định kỷ luật…) kèm ghi chú: chỗ nào là biến, điều luật nào làm căn cứ.",
        problem: "Mỗi luật sư soạn theo cách riêng; cùng một loại văn bản có nhiều phiên bản lệch nhau." },
      { title: "Admin chỉnh trong trình soạn", status: "roadmap", nodes: ["admin", "editor", "kb"], edges: [["admin", "editor"], ["kb", "editor"]],
        body: "Admin sửa trực tiếp như Google Docs/Claude Docs. Phần “Căn cứ” lấy thẳng từ kho luật, chỉ văn bản còn hiệu lực." },
      { title: "Chốt và khoá template", status: "roadmap", nodes: ["editor", "tpl"], edges: [["editor", "tpl"]],
        body: "Admin chốt: template được khoá, có số phiên bản, ai duyệt lúc nào. Sửa tiếp phải tạo phiên bản mới; bản cũ vẫn giữ để đối chiếu.",
        metric: [{ label: "Hiện có", value: "thư viện biểu mẫu (đang dùng / lưu trữ)" }] },
      { title: "Soạn văn bản từ template", status: "wip", nodes: ["tpl", "fill"], edges: [["tpl", "fill"]],
        body: "Khách hoặc luật sư chọn template, điền thông tin. Code điền biến (tên, ngày, số tiền), không cần AI.",
        metric: [{ label: "Đã có", value: "soạn văn bản hành chính theo NĐ 30/2020, xuất DOCX" }] },
      { title: "Model riêng gợi ý câu chữ", status: "roadmap", nodes: ["fill", "model", "kb"], edges: [["fill", "model"], ["kb", "model"]],
        body: "Chỉ ở chỗ cần diễn đạt (lý do, mô tả vụ việc), model tự train của LawVN gợi ý câu chữ. Model chỉ được dùng khi thắng cổng đo trên Kaggle.",
        problem: "Gọi AI cho mọi chữ thì tốn và khó kiểm; nên code làm phần lớn, AI chỉ ở chỗ cần." },
      { title: "Kiểm bằng code", status: "wip", nodes: ["model", "fill", "check"], edges: [["model", "check"], ["fill", "check"]],
        body: "Kiểm thể thức, căn cứ có thật và còn hiệu lực, số hiệu không bịa. Lỗi thì trả lại, không giao cho khách.",
        metric: [{ label: "Đã có", value: "kiểm trích dẫn bằng code cho câu trả lời hỏi đáp" }] },
      { title: "Giao và luật sư chốt", status: "done", nodes: ["check", "client"], edges: [["check", "client"]],
        body: "Văn bản giao kèm danh sách căn cứ. Bước duyệt của người (HITL) trước khi xuất đã có ở luồng soạn NĐ 30." },
    ],
  },
  {
    id: "thu-thap", title: "Thu thập dữ liệu có tuân thủ", minutes: 5,
    summary: "Web scraping từ nguồn chính thức: kiểm robots.txt, giãn cách, che PII, chờ duyệt, rồi mới vào kho.",
    nodes: [
      { id: "src", label: "Nguồn web", sub: "Công báo, bản án, chinhphu", x: 70, y: 150, kind: "web" },
      { id: "robots", label: "Kiểm robots.txt", sub: "cho phép mới đọc", x: 250, y: 70, kind: "code" },
      { id: "crawl", label: "Bộ thu thập", sub: "giãn cách 5 s, JS rendering", x: 250, y: 230, kind: "code" },
      { id: "parse", label: "Bóc tách", sub: "PDF/DOCX, điều khoản, ngày hiệu lực", x: 450, y: 150, kind: "code" },
      { id: "pii", label: "Che PII", sub: "luật + NER", x: 640, y: 70, kind: "code" },
      { id: "embed", label: "Embedding", sub: "Kaggle GPU", x: 640, y: 230, kind: "model" },
      { id: "review", label: "Chờ duyệt", sub: "/upload", x: 830, y: 150, kind: "person" },
      { id: "kb", label: "Kho luật", sub: "dùng để trả lời", x: 1010, y: 150, kind: "store" },
    ],
    edges: [
      { from: "src", to: "robots" }, { from: "robots", to: "crawl", label: "cho phép" }, { from: "src", to: "crawl" },
      { from: "crawl", to: "parse" }, { from: "parse", to: "pii" }, { from: "parse", to: "embed" },
      { from: "pii", to: "review" }, { from: "embed", to: "review" }, { from: "review", to: "kb", label: "duyệt" },
    ],
    steps: [
      { title: "Chọn nguồn chính thức", status: "done", nodes: ["src"], edges: [],
        body: "Chỉ nguồn công khai: Công báo, Cổng công bố bản án, chinhphu.vn. Nguồn có thử thách chống bot (quochoi.vn) hoặc từ chối bot (pbgdpl.gov.vn) thì không dùng.",
        metric: [{ label: "Nguồn", value: "9 (4 dùng, 3 tìm tiếp, 2 không dùng)" }] },
      { title: "Kiểm robots.txt trước", status: "done", nodes: ["src", "robots"], edges: [["src", "robots"]],
        body: "Đọc robots.txt; đường dẫn bị cấm thì dừng. Không vượt CAPTCHA, không đăng nhập hộ, User-Agent ghi rõ.",
        problem: "Cào bừa thì bị chặn, và với sản phẩm pháp lý còn là rủi ro pháp lý." },
      { title: "Thu thập có giãn cách", status: "done", nodes: ["robots", "crawl"], edges: [["robots", "crawl"]],
        body: "Mỗi yêu cầu cách nhau ≥ 5 giây; trang dựng bằng JavaScript thì dùng Chromium; lỗi mạng thì đợi rồi thử lại.",
        metric: [{ label: "Đã lấy", value: "200 bản án, 19 văn bản luật đợt 2" }] },
      { title: "Bóc tách và đọc ngày hiệu lực", status: "done", nodes: ["crawl", "parse"], edges: [["crawl", "parse"]],
        body: "PDF/DOCX thành điều, khoản, điểm. Code đọc câu “có hiệu lực từ ngày…” trong văn bản, không để AI đoán ngày." },
      { title: "Che PII và tạo embedding", status: "done", nodes: ["parse", "pii", "embed"], edges: [["parse", "pii"], ["parse", "embed"]],
        body: "Bản án đã ẩn danh một phần vẫn chạy bộ che. Văn bản lớn tạo embedding trên Kaggle GPU, máy nhà chỉ ghi vector về.",
        metric: [{ label: "Kaggle vs máy nhà", value: "độ tương đồng vector ≥ 0,9998" }] },
      { title: "Người duyệt rồi mới dùng", status: "done", nodes: ["pii", "embed", "review", "kb"], edges: [["pii", "review"], ["embed", "review"], ["review", "kb"]],
        body: "Mọi văn bản mới nằm ở /upload chờ duyệt; chỉ văn bản đã duyệt mới được dùng để trả lời." },
      { title: "Mạng xã hội và cộng đồng", status: "roadmap", nodes: ["src"], edges: [],
        body: "Chỉ qua đường hợp lệ: API chính thức (Graph API, Meta Content Library), dữ liệu có giấy phép, người dùng tự gửi có đồng ý. Thêm tab mới trên cùng khung nguồn." },
    ],
  },
];
