"use client";

/* Bấm Gửi: nếu câu hỏi có đoạn nhạy cảm (tên người, công ty, số, tình tiết) thì cho chọn làm mờ
   trước khi gửi; không có gì nhạy cảm thì Composer gửi thẳng, không mở cửa sổ này. */
import { useEffect, useState } from "react";

import { emit } from "@/components/help/Coach";
import { apiFetch } from "@/lib/api";

export type Span = {
  id: string; type: string; group: string; entity: string; text: string;
  start: number; end: number; suggestion: string; default: string;
};

const LABEL: Record<string, string> = { pseudonym: "Thay tên giả", generalize: "Làm chung chung", keep: "Giữ nguyên" };
const GROUP: Record<string, string> = {
  person: "Tên người", organization: "Công ty, tổ chức", contact: "Địa chỉ, số", sensitive_fact: "Tình tiết nhạy cảm",
};

export async function detectSpans(text: string): Promise<Span[]> {
  const r = await apiFetch("/api/intake/detect", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
  }).catch(() => null);
  return r?.ok ? (await r.json()).spans : [];
}

export default function SendReview({ text, spans, onCancel, onSend }: {
  text: string;
  spans: Span[];
  onCancel: () => void;
  onSend: (masked: string) => void;
}) {
  const [decisions, setDecisions] = useState<Record<string, { action: string; replacement?: string }>>({});
  const [preview, setPreview] = useState("");
  const [kept, setKept] = useState(0);

  useEffect(() => {
    const t = setTimeout(async () => {
      const r = await apiFetch("/api/intake/apply", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, decisions }),
      }).catch(() => null);
      if (r?.ok) { const b = await r.json(); setPreview(b.text); setKept(b.kept); }
    }, 200);
    return () => clearTimeout(t);
  }, [text, decisions]);

  const setAction = (s: Span, action: string) => {
    setDecisions((d) => ({ ...d, [s.id]: { ...d[s.id], action } }));
    emit("mask-chosen");
  };
  const setRepl = (s: Span, replacement: string) => setDecisions((d) => {
    const next = { ...d };
    spans.filter((x) => x.entity === s.entity).forEach((x) => { next[x.id] = { action: next[x.id]?.action || x.default, replacement }; });
    return next;
  });

  return (
    <div className="vi-backdrop" role="dialog" aria-modal="true" aria-label="Làm mờ trước khi gửi">
      <div className="vi-panel">
        <header className="vi-head">
          <strong>Làm mờ thông tin trước khi gửi</strong>
          <button className="icon-btn" onClick={onCancel} aria-label="Đóng">✕</button>
        </header>
        <div className="vi-body">
          <p className="vi-note">Câu hỏi có {spans.length} đoạn nhạy cảm. Mặc định đã làm mờ; giữ nguyên đoạn nào cần để hiểu vụ việc.</p>
          <div className="vi-spans" data-tour="voice-spans">
            {spans.map((s) => {
              const act = decisions[s.id]?.action || s.default;
              return (
                <div key={s.id} className="vi-span">
                  <div className="vi-span-text"><small>{GROUP[s.group] || s.group}</small> “{s.text}”</div>
                  <div className="vi-span-ctrl">
                    {(s.type === "TÌNH_TIẾT" ? ["generalize", "keep"] : ["pseudonym", "keep"]).map((a) => (
                      <label key={a}><input type="radio" name={s.id} checked={act === a} onChange={() => setAction(s, a)} /> {LABEL[a]}</label>
                    ))}
                    {act !== "keep" && s.type !== "TÌNH_TIẾT" && (
                      <input className="vi-repl" value={decisions[s.id]?.replacement ?? s.suggestion}
                        onChange={(e) => setRepl(s, e.target.value)} aria-label="Tên thay thế" />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <label className="vi-label">Bản sẽ được gửi</label>
          <div className="vi-preview">{preview}</div>
          {kept > 0 && <p className="vi-warn">Bạn giữ nguyên {kept} đoạn nhạy cảm; hệ thống vẫn che lại trước khi gửi tới AI bên ngoài.</p>}
          <div className="vi-actions">
            <button className="vi-btn" onClick={onCancel}>Sửa lại</button>
            <button className="vi-btn" onClick={() => onSend(text)}>Gửi bản gốc</button>
            <button className="vi-btn primary" disabled={!preview} onClick={() => onSend(preview)}>Gửi bản đã làm mờ</button>
          </div>
        </div>
      </div>
    </div>
  );
}
