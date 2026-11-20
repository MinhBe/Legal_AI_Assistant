"use client";

/* Các phần gắn dưới một câu trả lời: thẻ phê duyệt khi từ chối, gợi ý câu hỏi
   chuẩn hơn, luồng tra cứu, các mục trả lời, và trích dẫn. */
import { useState } from "react";
import { emit } from "@/components/help/Coach";

import { IconCheck, IconChevron, IconLock, IconRefresh, IconSearch } from "@/components/chat/icons";
import type { Calc, FactValue, Facts, Citation, EscalateStatus, Hints, Section, TimeFrame, Verifier } from "@/lib/chat/types";

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
    <div className="citations" data-tour="citations">
      <div className="chip-row">
        {citations.map((c, j) => {
          const n = c.n ?? j + 1;
          const isOpen = open === n;
          return (
            <button
              key={j}
              className={`chip ${isOpen ? "active" : ""}`}
              onClick={() => { setOpen(isOpen ? null : n); if (!isOpen) emit("citation-opened"); }}
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

/* hộp "Bảng tình tiết" (I1): trường đã biết kèm nguồn và độ chắc, trường quyết định
   còn thiếu thì ghi "chưa rõ", kèm chip câu hỏi lại bấm được */
const FACT_ROWS: { key: string; label: string }[] = [
  { key: "contract_type", label: "Loại hợp đồng" },
  { key: "term_months", label: "Thời hạn hợp đồng" },
  { key: "start_date", label: "Bắt đầu làm việc" },
  { key: "end_date", label: "Ngày chấm dứt" },
  { key: "event_date", label: "Ngày sự kiện" },
  { key: "act", label: "Hành vi, sự kiện" },
  { key: "monthly_salary", label: "Lương tháng" },
  { key: "notice_given_days", label: "Ngày đã báo trước" },
  { key: "unemployment_insured_months", label: "Tháng đóng BHTN" },
  { key: "procedure", label: "Thủ tục đã làm" },
  { key: "documents", label: "Hồ sơ hiện có" },
];
/* trường quyết định kết quả: thiếu thì hiện "chưa rõ" thay vì ẩn */
const DECISIVE = ["contract_type", "term_months", "start_date", "monthly_salary"];
const CONTRACT_LABEL: Record<string, string> = {
  khong_xac_dinh_thoi_han: "không xác định thời hạn",
  xac_dinh_thoi_han: "xác định thời hạn",
  thu_viec: "thử việc",
  khong_ro: "chưa rõ",
};
const ACT_LABEL: Record<string, string> = {
  sa_thai: "sa thải",
  don_phuong_cham_dut_nld: "người lao động đơn phương chấm dứt",
  don_phuong_cham_dut_nsdld: "người sử dụng lao động đơn phương chấm dứt",
  ky_luat: "kỷ luật",
  no_luong: "chưa trả lương",
  khac: "khác",
};
const vnd = (n: number) => `${new Intl.NumberFormat("vi-VN").format(n)} đồng`;

function factText(key: string, f: FactValue): string {
  const v = f.value;
  if (key === "contract_type") return CONTRACT_LABEL[String(v)] ?? String(v);
  if (key === "act") return ACT_LABEL[String(v)] ?? String(v);
  if (key === "monthly_salary") return typeof v === "number" ? vnd(v) : String(v);
  if (key === "term_months") return `${v} tháng`;
  if (key === "notice_given_days") return `${v} ngày`;
  if (key === "unemployment_insured_months") return `${v} tháng`;
  if (key === "start_date" || key === "end_date" || key === "event_date") return dmy(String(v));
  return Array.isArray(v) ? v.join("; ") : String(v);
}

export function FactsBox({
  facts,
  followUps,
  onAsk,
}: {
  facts: Facts;
  followUps: string[];
  onAsk: (q: string) => void;
}) {
  const rows = FACT_ROWS.flatMap(({ key, label }) => {
    const f = facts.facts?.[key];
    if (f) {
      return [
        {
          key,
          label,
          value: factText(key, f),
          meta: `${f.source} · ${Math.round(f.confidence * 100)}%`,
          unknown: false,
        },
      ];
    }
    return DECISIVE.includes(key)
      ? [{ key, label, value: "chưa rõ", meta: "", unknown: true }]
      : [];
  });
  if (rows.length === 0 && followUps.length === 0) return null;
  return (
    <div className="facts">
      <div className="facts-title">Bảng tình tiết</div>
      {rows.map((r) => (
        <div className="facts-row" key={r.key}>
          <span className="facts-label">{r.label}</span>
          <span className={`facts-val ${r.unknown ? "facts-unknown" : ""}`}>{r.value}</span>
          {r.meta && <span className="facts-meta">{r.meta}</span>}
        </div>
      ))}
      {followUps.length > 0 && (
        <div className="facts-follow-ups">
          <span className="facts-label">Cần biết thêm</span>
          <div className="facts-chips">
            {followUps.map((q) => (
              <button key={q} className="facts-chip" onClick={() => onAsk(q)}>
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* hộp "Kết quả tính" (I2): từng khoản do code tính, kèm bước tính và căn cứ */
export function CalcBox({ calc }: { calc: Calc }) {
  if (!calc.items || calc.items.length === 0) return null;
  return (
    <div className="calc-res">
      <div className="calc-res-title">Kết quả tính</div>
      {calc.items.map((item) => (
        <div className="calc-res-card" key={`${item.kind}-${item.value}`}>
          <div className="calc-res-head">
            <span className="calc-res-name">{item.title}</span>
            <span className="calc-res-value">
              {item.unit === "đồng" ? vnd(item.value) : `${item.value} ${item.unit}`}
            </span>
          </div>
          {item.steps?.length > 0 && (
            <ol className="calc-res-steps">
              {item.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          )}
          <div className="calc-res-basis">
            {(item.basis ?? []).map((b, i) => (
              <span className="calc-res-basis-item" key={i} title={b.doc_id}>
                {b.label}
              </span>
            ))}
            {item.version && <span className="calc-res-version">{item.version}</span>}
          </div>
          <div className="calc-res-warning">
            {item.note || "Kết quả tính tự động — cần luật sư đối chiếu"}
          </div>
        </div>
      ))}
    </div>
  );
}

/* hộp "Tham khảo thêm" (PR1): án lệ/bài toán đã duyệt — chỉ để đọc, không phải căn cứ. */
const PREC_STATUS: Record<string, string> = {
  dang_ap_dung: "đang áp dụng",
  bi_huy_bo: "bị hủy bỏ",
  chua_ro: "chưa rõ",
};

export function HintsBox({ hints }: { hints: Hints }) {
  const precedents = hints.precedents ?? [];
  const problems = hints.problems ?? [];
  if (precedents.length === 0 && problems.length === 0) return null;
  return (
    <div className="prec-hint">
      <div className="prec-hint-title">Tham khảo thêm</div>
      {precedents.length > 0 && (
        <>
          <div className="prec-hint-label">
            Án lệ có thể liên quan — chưa được luật sư xác nhận áp dụng cho trường hợp này
          </div>
          {precedents.map((p) => (
            <a
              key={`${p.number}-${p.url}`}
              className="prec-hint-item"
              href={p.url || "#"}
              target="_blank"
              rel="noreferrer"
            >
              <span className="prec-hint-num">Án lệ {p.number}</span>
              <span className="prec-hint-name">{p.title}</span>
              <span className={`prec-hint-status ${p.status}`}>
                {PREC_STATUS[p.status] ?? p.status}
              </span>
              <span className="prec-hint-sim">{Math.round(p.similarity * 100)}%</span>
            </a>
          ))}
        </>
      )}
      {problems.map((p) => (
        <a key={p.id} className="prec-hint-item" href="/bai-toan">
          <span className="prec-hint-name">{p.title}</span>
          <span className="prec-hint-label">
            Bài toán đã được luật sư {p.approved_by || "(chưa rõ)"} duyệt
          </span>
        </a>
      ))}
    </div>
  );
}

/* nhãn kết quả Verifier (T5): căn cứ hợp lệ, hoặc danh sách căn cứ bị loại */
export function VerifierBadge({ v }: { v: Verifier }) {
  const [open, setOpen] = useState(false);
  const dropped = v.dropped?.length ?? 0;
  if (v.ok) {
    const valid = Math.max(0, v.checked - dropped);
    return (
      <div className="verifier verifier-ok">✓ Đã kiểm tra căn cứ: {valid} trích dẫn hợp lệ</div>
    );
  }
  return (
    <div className="verifier verifier-warn">
      <button className="verifier-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        ⚠ Đã loại {dropped} căn cứ không hợp lệ
      </button>
      {open && (v.problems?.length ?? 0) > 0 && (
        <ul className="verifier-problems">
          {v.problems.map((p, i) => (
            <li className="verifier-problem" key={i}>{p.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
