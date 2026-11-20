"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  ApprovalCard, CalcBox, CitationList, FactsBox, HintsBox, SectionAccordion, StepTimeline, SuggestRewrite,
  TimeFrameBox, VerifierBadge,
} from "@/components/chat/AnswerParts";
import { IconGraph } from "@/components/chat/icons";
import { useAuth } from "@/lib/auth";
import type { Msg, Reading, Risk } from "@/lib/chat/types";
import type { MODE_TEXT } from "@/lib/mode";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

/* Chip điểm rủi ro (R1): ca vào hàng đợi luật sư thì mở ra được lý do. */
function RiskBadge({ risk }: { risk: Risk }) {
  if (risk.queue) {
    return (
      <details className="risk risk-queued">
        <summary>Đã chuyển luật sư xem lại (điểm rủi ro {risk.score})</summary>
        <ul className="risk-reasons">
          {risk.reasons.map((r) => (
            <li key={r.code}>{r.message}</li>
          ))}
        </ul>
      </details>
    );
  }
  if (typeof risk.score !== "number" || risk.score <= 0) return null;
  return <span className="risk risk-low">Rủi ro thấp ({risk.score})</span>;
}

/* Chip cách đọc câu không dấu (ML2). */
function ReadingChip({ reading }: { reading: Reading }) {
  if (reading.lang === "vi") {
    return <span className="reading reading-vi">Đã hiểu là tiếng Việt: «{reading.vi_text}»</span>;
  }
  return <span className="reading reading-en">Understood as English</span>;
}

export default function MessageList({
  messages, threadId, listRef, text, onAsk, onUseSuggestion, onIgnoreSuggestion, onEscalate, onDeny,
}: {
  messages: Msg[];
  text: (typeof MODE_TEXT)["law"];
  threadId: string | null;
  listRef: React.RefObject<HTMLDivElement | null>;
  onAsk: (q: string) => void;
  onUseSuggestion: (msgIdx: number, q: string) => void;
  onIgnoreSuggestion: (msgIdx: number) => void;
  onEscalate: (question: string, msgIdx: number) => void;
  onDeny: (msgIdx: number) => void;
}) {
  // the user turn just above an AI message is the question it answered
  const questionBefore = (i: number) => (messages[i - 1]?.role === "user" ? messages[i - 1].content : "");

  // AUTH1: vai trò không có quyền `escalate` thì không thấy nút gửi luật sư
  const canEscalate = useAuth().can("escalate");

  return (
    <div className="messages" ref={listRef}>
      {messages.length === 0 ? (
        <div className="messages-inner">
          <div className="empty">
            <div className="logo" style={{ width: 44, height: 44, fontSize: 20, borderRadius: 12 }}>L</div>
            <h2>{text.emptyTitle}</h2>
            <p>{text.emptySub}</p>
            <div className="suggestions">
              {text.suggestions.map((s) => (
                <button key={s} className="suggestion" onClick={() => onAsk(s)}>
                  {s}
                </button>
              ))}
            </div>
            <Link href="/graph" className="empty-graph-btn">
              <IconGraph /> Xem Knowledge Graph embedding
            </Link>
          </div>
        </div>
      ) : (
        <div className="messages-inner">
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="bubble">
                {/* bước đang chạy (realtime) */}
                {m.step && (
                  <div className="step">
                    <span className="dot" /> {m.step}…
                  </div>
                )}

                {m.role === "ai" ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || (m.step ? "" : "…")}</ReactMarkdown>
                ) : (
                  m.content
                )}

                {m.role === "ai" && m.facts && (
                  <FactsBox facts={m.facts} followUps={m.facts.follow_ups ?? []} onAsk={onAsk} />
                )}

                {m.role === "ai" && m.calc && <CalcBox calc={m.calc} />}

                {m.role === "ai" && m.timeframe && <TimeFrameBox tf={m.timeframe} />}

                {m.role === "ai" && (m.sections?.length ?? 0) > 0 && (
                  <SectionAccordion sections={m.sections!} />
                )}

                {m.role === "ai" && m.prerecorded && (
                  <div className="domain-badge prerecorded" title="Máy chủ AI đang chậm: hiện câu trả lời đã chạy thật trước đó">
                    Bản ghi sẵn
                  </div>
                )}

                {m.role === "ai" && m.domain_label && !m.refusal && (
                  <div className="domain-badge" title="Lĩnh vực của văn bản được trích dẫn">
                    Lĩnh vực: {m.domain_label}
                  </div>
                )}

                {m.role === "ai" && m.verifier && <VerifierBadge v={m.verifier} />}

                {m.role === "ai" && m.hints && <HintsBox hints={m.hints} />}

                {m.role === "ai" && m.reading && <ReadingChip reading={m.reading} />}

                {m.role === "ai" && m.risk && <RiskBadge risk={m.risk} />}

                {/* R4: mức tự chủ 1 gửi khách ngay nhưng phải nói rõ là chưa xác nhận */}
                {m.role === "ai" && m.risk?.unconfirmed && (
                  <span className="unconfirmed">Chưa được luật sư xác nhận</span>
                )}

                {/* R7: không có luật sư trực thì câu trả lời chưa được duyệt ngay */}
                {m.role === "ai" && m.risk?.no_lawyer && (
                  <span className="unconfirmed">
                    Hiện không có luật sư trực: câu trả lời chưa được gửi duyệt ngay
                  </span>
                )}

                {m.suggested_query && m.role === "ai" && (
                  <SuggestRewrite
                    suggested={m.suggested_query}
                    reason={m.suggest_reason || ""}
                    used={m.suggest_used}
                    onUse={() => onUseSuggestion(i, m.suggested_query!)}
                    onIgnore={() => onIgnoreSuggestion(i)}
                  />
                )}

                {/* thẻ phê duyệt chỉ hiện khi bị từ chối (và khi được phép gửi luật sư) */}
                {canEscalate && m.refusal && m.role === "ai" && (
                  <ApprovalCard
                    question={questionBefore(i)}
                    threadId={threadId}
                    status={m.escalate_status ?? "pending"}
                    reply={m.escalate_reply}
                    onApprove={() => onEscalate(questionBefore(i), i)}
                    onDeny={() => onDeny(i)}
                  />
                )}

                {m.role === "ai" && !m.step && (m.steps_log?.length ?? 0) > 0 && (
                  <StepTimeline steps={m.steps_log!} />
                )}

                {m.citations && m.citations.length > 0 && (
                  <CitationList citations={m.citations} />
                )}

                {m.role === "ai" && m.record_id && (
                  <a
                    className="record-link"
                    href={`${API_BASE}/api/answers/${m.record_id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Hồ sơ tra cứu #{m.record_id}
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
