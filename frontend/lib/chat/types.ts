export type Citation = { n?: number; node_id: string; display?: string; text?: string };
export type Section = { title: string; detail: string; citations: Citation[] };

/* Khung thời gian do backend chốt (T2): luật áp dụng tại ngày sự kiện và các thay đổi sau đó. */
export type TimeFrameDoc = { doc_id: string; title?: string | null; number?: string | null };
export type TimeFrameChange = TimeFrameDoc & { effective_date?: string | null; replaces: string[] };
export type TimeFrameUpcoming = TimeFrameDoc & { effective_date?: string | null; status?: string };
export type TransitionRule = {
  doc_key: string;
  condition: string;
  outcome: string;
  provision_ref?: string | null;
  note?: string | null;
};
export type TimeFrameVerify = {
  doc_id: string;
  title?: string | null;
  base_doc_id: string;
  base_title: string;
  since?: string | null;
  reason: string;
};
export type TimeFrame = {
  event_date: string | null;
  event_date_source: string;
  advice_date: string;
  as_of: string;
  applicable: TimeFrameDoc[];
  changes_after: TimeFrameChange[];
  upcoming: TimeFrameUpcoming[];
  transition_rules: TransitionRule[];
  verify: TimeFrameVerify[];
  flags: string[];
};
/* Verifier bằng code (T5): căn cứ có thật, còn hiệu lực tại ngày sự kiện, trích nguyên văn. */
export type VerifierProblem = {
  check: "exists" | "in_force" | "quotes";
  node_id?: string;
  quote?: string;
  message: string;
};
export type Verifier = {
  ok: boolean;
  checked: number;
  problems: VerifierProblem[];
  dropped: string[];
};
/* Vòng phê duyệt có người thật:
   pending  -> người dùng chưa quyết gửi hay không
   denied   -> người dùng chọn không gửi
   waiting  -> đã gửi, chờ chuyên gia trên /dashboard ("approved" là giá trị cũ cùng nghĩa)
   answered -> chuyên gia đã duyệt và trả lời (escalate_reply)
   rejected -> chuyên gia từ chối (escalate_reply là lý do) */
export type EscalateStatus = "pending" | "denied" | "waiting" | "approved" | "answered" | "rejected" | null;

/* Điểm rủi ro do backend chấm bằng quy tắc (R1): ca rủi ro cao vào hàng đợi luật sư.
   Mức tự chủ theo loại ca (R4): mức 1 thì câu trả lời mang nhãn "chưa xác nhận";
   không có luật sư trực (R7) thì `no_lawyer` bật. */
export type RiskReason = { code: string; weight: number | "inf"; message: string };
export type Risk = {
  score: number | "inf";
  queue: boolean;
  reasons: RiskReason[];
  case_id?: string;
  case_type?: string;
  autonomy_level?: number;
  unconfirmed?: boolean;
  no_lawyer?: boolean;
};

/* Bảng tình tiết do backend trích từ câu hỏi (I1): nguồn và độ chắc của từng trường. */
export type FactValue = { value: string | number | string[]; source: string; confidence: number };
export type Facts = { facts: Record<string, FactValue>; follow_ups: string[] };

/* Kết quả máy tính lao động (I2): code tính, LLM không tham gia. */
export type CalcBasis = { doc_id: string; label: string; node_id?: string };
export type CalcItem = {
  kind: string;
  title: string;
  value: number;
  unit: string;
  steps: string[];
  basis: CalcBasis[];
  version: string;
  note?: string;
};
export type Calc = { items: CalcItem[] };

export type Msg = {
  role: "user" | "ai";
  content: string;
  step?: string;
  citations?: Citation[];
  steps_log?: string[];
  refusal?: boolean;
  escalate_id?: string;
  escalate_status?: EscalateStatus;
  escalate_reply?: string;
  suggested_query?: string;
  suggest_reason?: string;
  suggest_used?: boolean;
  sections?: Section[];
  timeframe?: TimeFrame;
  verifier?: Verifier;
  record_id?: string;
  risk?: Risk;
  facts?: Facts;
  calc?: Calc;
};

export type Conversation = { id: string; title: string; messages: Msg[] };
