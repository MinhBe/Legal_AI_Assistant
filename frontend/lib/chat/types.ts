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
};

export type Conversation = { id: string; title: string; messages: Msg[] };
