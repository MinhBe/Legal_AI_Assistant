"use client";

/* Các phần gắn dưới một câu trả lời: thẻ phê duyệt khi từ chối, gợi ý câu hỏi
   chuẩn hơn, luồng tra cứu, các mục trả lời, và trích dẫn. */
import { useState } from "react";

import { IconCheck, IconChevron, IconLock, IconRefresh, IconSearch } from "@/components/chat/icons";
import type { Citation, EscalateStatus, Section, TimeFrame } from "@/lib/chat/types";

export function ApprovalCard({
  question,
  threadId,
  status,
  reply,
  onApprove,
  onDeny,
}: {
  question: string;
  threadId: string | null;
  status: EscalateStatus;
  reply?: string;
  onApprove: () => void;
  onDeny: () => void;
}) {
  // "approved" is what cards sent before the expert step existed were saved as
  if (status === "waiting" || status === "approved") {
    return (
      <div className="approval-card">
        <div className="approval-header">
          <span className="approval-icon"><IconLock /></span>
          <span className="approval-title">ĐANG CHỜ CHUYÊN GIA DUYỆT</span>
          <span className="approval-badge">human-in-the-loop</span>
        </div>
        <p className="approval-note">Câu hỏi đã được gửi. Câu trả lời của chuyên gia sẽ hiện ở đây khi được duyệt, không cần tải lại trang.</p>
      </div>
    );
  }
  if (status === "answered") {
    return (
      <div className="approval-card approved">
        <div className="approval-header">
          <span className="approval-icon"><IconCheck /></span>
          <span className="approval-title">CHUYÊN GIA ĐÃ TRẢ LỜI</span>
          <span className="approval-badge">human-in-the-loop</span>
        </div>
        <p className="approval-note approval-reply">{reply}</p>
      </div>
    );
  }
  if (status === "rejected") {
    return (
      <div className="approval-card denied">
        <div className="approval-header">
          <span className="approval-title">CHUYÊN GIA TỪ CHỐI</span>
        </div>
        <p className="approval-note approval-reply">{reply || "Yêu cầu không được chuyên gia xử lý."}</p>
      </div>
    );
  }
  if (status === "denied") {
    return (
      <div className="approval-card denied">
        <div className="approval-header">
          <span className="approval-title">ĐÃ TỪ CHỐI</span>
        </div>
        <p className="approval-note">Câu hỏi không được gửi đi.</p>
      </div>
    );
  }

  return (
    <div className="approval-card">
      <div className="approval-header">
        <span className="approval-icon"><IconLock /></span>
        <span className="approval-title">CẦN PHÊ DUYỆT</span>
        <span className="approval-badge">escalate_refusal</span>
      </div>
      <p className="approval-desc">Trợ lý muốn gửi câu hỏi này cho <strong>chuyên gia</strong> trả lời trực tiếp và bổ sung dữ liệu.</p>
      <div className="approval-fields">
        <div className="af-row">
          <div className="af-col">
            <div className="af-label">CÂU HỎI</div>
            <div className="af-val">{question}</div>
          </div>
          <div className="af-col">
            <div className="af-label">HÀNH ĐỘNG</div>
            <div className="af-val">Ghi nhận &amp; thông báo</div>
          </div>
        </div>
        <div className="af-row">
          <div className="af-col">
            <div className="af-label">THREAD</div>
            <div className="af-val">{threadId || "—"}</div>
          </div>
          <div className="af-col">
            <div className="af-label">TRẠNG THÁI</div>
            <div className="af-val">Chờ phê duyệt</div>
          </div>
        </div>
      </div>
      <div className="approval-actions">
        <button className="btn-approve" onClick={onApprove}><IconCheck /> PHÊ DUYỆT</button>
        <button className="btn-deny" onClick={onDeny}>✕ TỪ CHỐI</button>
        <span className="approval-footer-note">câu hỏi chưa được gửi cho đến khi bạn phê duyệt</span>
      </div>
    </div>
  );
}

export function StepTimeline({ steps }: { steps: string[] }) {
  const [open, setOpen] = useState(false);
  if (!steps || steps.length === 0) return null;
  return (
    <div className="step-timeline">
      <button className="step-toggle" onClick={() => setOpen((v) => !v)}>
        <IconChevron open={open} />
        <IconSearch />
        <span>Luồng tra cứu ({steps.length} bước)</span>
      </button>
      {open && (
        <div className="step-list">
          {steps.map((s, i) => (
            <div key={i} className="step-row">
              <span className="step-dot-done"><IconCheck /></span>
              <span>{s}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* từng ý của câu trả lời thành một mục đóng/mở */
export function SectionAccordion({ sections }: { sections: Section[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!sections || sections.length === 0) return null;
  return (
    <div className="section-accordion">
      {sections.map((s, i) => {
        const isOpen = open === i;
        return (
          <div key={i} className={`section-item ${isOpen ? "open" : ""}`}>
            <button
              className="section-toggle"
              onClick={() => setOpen(isOpen ? null : i)}
              aria-expanded={isOpen}
            >
              <IconChevron open={isOpen} />
              <span className="section-num">{i + 1}.</span>
              <span className="section-title">{s.title}</span>
            </button>
            {isOpen && (
              <div className="section-body">
                <div className="section-detail">{s.detail}</div>
                {s.citations && s.citations.length > 0 && (
                  <div className="section-sources">
                    {s.citations.map((c, j) => (
                      <span
                        key={j}
                        className="chip"
                        title={c.text || c.node_id}
                        onClick={() => {
                          const el = document.getElementById(`cite-panel-${c.node_id}`);
                          if (el) el.scrollIntoView({ behavior: "smooth" });
                        }}
                      >
                        {c.display || c.node_id}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* đề xuất câu hỏi pháp lý chuẩn hơn khi không tìm được căn cứ */
export function SuggestRewrite({
  suggested,
  reason,
  used,
  onUse,
  onIgnore,
}: {
  suggested: string;
  reason: string;
  used?: boolean;
  onUse: () => void;
  onIgnore: () => void;
}) {
  if (used) {
    return (
      <div className="rewrite-card used">
        <span className="rewrite-icon"><IconRefresh /></span>
        <span className="rewrite-used-label">Đã tìm lại với câu hỏi chuẩn pháp lý.</span>
      </div>
    );
  }
  return (
    <div className="rewrite-card">
      <div className="rewrite-header">
        <span className="rewrite-icon"><IconRefresh /></span>
        <span className="rewrite-title">Đề xuất câu hỏi pháp lý chuẩn hơn</span>
      </div>
      {reason && <p className="rewrite-reason">{reason}</p>}
      <div className="rewrite-suggested">"{suggested}"</div>
      <div className="rewrite-actions">
        <button className="btn-use-rewrite" onClick={onUse}>
          <IconCheck /> Dùng câu này
        </button>
        <button className="btn-deny" onClick={onIgnore}>✕ Bỏ qua</button>
      </div>
    </div>
  );
}

/* chip trích dẫn, bấm để mở/đóng nguyên văn */
export function CitationList({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="citations">
      <div className="chip-row">
        {citations.map((c, j) => {
          const n = c.n ?? j + 1;
          const isOpen = open === n;
          return (
            <button
              key={j}
              className={`chip ${isOpen ? "active" : ""}`}
              onClick={() => setOpen(isOpen ? null : n)}
              aria-expanded={isOpen}
            >
              <span className="n">[{n}]</span> {c.display || c.node_id}
              <span className="chip-arrow">{isOpen ? "▲" : "▼"}</span>
            </button>
          );
        })}
      </div>

      {open !== null && (() => {
        const c = citations.find((x, j) => (x.n ?? j + 1) === open);
        if (!c) return null;
        return (
          <div className="citation-panel">
            <div className="citation-panel-head">{c.display || c.node_id}</div>
            <div className="citation-panel-body">{c.text || "Không có nội dung."}</div>
          </div>
        );
      })()}
    </div>
  );
}

/* hộp "Khung thời gian": backend chốt luật áp dụng tại ngày sự kiện */
const dmy = (iso?: string | null) => (iso ? iso.split("-").reverse().join("/") : "—");
const docLabel = (d: { title?: string | null; number?: string | null; doc_id: string }) =>
  d.title || d.number || d.doc_id;

const OUTCOME: Record<string, string> = {
  old_law: "áp dụng luật cũ",
  new_law: "áp dụng luật mới",
  mixed: "kết hợp luật cũ và mới",
};

export function TimeFrameBox({ tf }: { tf: TimeFrame }) {
  const rows: { label: string; items: string[] }[] = [
    {
      label: "Ngày sự kiện",
      items: [
        tf.event_date
          ? `${dmy(tf.event_date)} (${tf.event_date_source})`
          : `không nêu — dùng ngày tư vấn ${dmy(tf.as_of)}`,
      ],
    },
    { label: "Luật áp dụng", items: (tf.applicable ?? []).map(docLabel) },
    {
      label: "Thay đổi sau sự kiện",
      items: (tf.changes_after ?? []).map(
        (c) => `${docLabel(c)} — hiệu lực ${dmy(c.effective_date)}`,
      ),
    },
    {
      label: "Sắp thay đổi (không làm căn cứ)",
      items: (tf.upcoming ?? []).map(
        (u) => `${docLabel(u)} — ${dmy(u.effective_date)}${u.status ? ` (${u.status})` : ""}`,
      ),
    },
    {
      label: "Điều khoản chuyển tiếp đã xét",
      items: (tf.transition_rules ?? []).map(
        (r) => `${r.doc_key}: ${r.condition} → ${OUTCOME[r.outcome] ?? r.outcome}`,
      ),
    },
    {
      label: "Cần xác minh (văn bản dựa trên luật đã bị thay)",
      items: (tf.verify ?? []).map((v) => v.reason),
    },
  ];
  return (
    <div className="timeframe">
      <div className="timeframe-title">Khung thời gian</div>
      {rows.map((r) => (
        <div className="timeframe-row" key={r.label}>
          <span className="timeframe-label">{r.label}</span>
          <span className="timeframe-val">
            {r.items.length === 0 ? <span className="timeframe-empty">không có</span> : r.items.join("; ")}
          </span>
        </div>
      ))}
      {(tf.flags ?? []).length > 0 && (
        <div className="timeframe-flags">
          {tf.flags.map((f, i) => (
            <span className="timeframe-flag" key={i}>⚠ {f}</span>
          ))}
        </div>
      )}
    </div>
  );
}
