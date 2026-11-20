"use client";

/* Chỉ dẫn từng bước: làm tối nền, chiếu sáng đúng phần tử cần bấm, bước có `waitFor` chỉ đi
   tiếp khi người dùng làm đúng thao tác. Nội dung ở lib/help/content.ts. */
import { useCallback, useEffect, useState } from "react";

import { type TourStep } from "@/lib/help/content";

export function emit(name: string) {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(`lawvn:${name}`));
}

type Rect = { top: number; left: number; width: number; height: number };

function findTarget(target: string): HTMLElement | null {
  const all = document.querySelectorAll<HTMLElement>(`[data-tour="${target}"]`);
  // phần tử cuối là cái mới nhất (trích dẫn của câu trả lời gần nhất)
  for (let i = all.length - 1; i >= 0; i--) {
    const r = all[i].getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return all[i];
  }
  return null;
}

export default function Coach({ steps, startAt = 0, onClose }: {
  steps: TourStep[];
  startAt?: number;
  onClose: (completed: boolean) => void;
}) {
  const [i, setI] = useState(startAt);
  const [rect, setRect] = useState<Rect | null>(null);
  const step = steps[i];

  const next = useCallback(() => {
    if (i + 1 >= steps.length) onClose(true);
    else setI(i + 1);
  }, [i, steps.length, onClose]);

  // theo dõi vị trí phần tử (cuộn, đổi kích thước, phần tử xuất hiện muộn)
  useEffect(() => {
    if (!step) return;
    let raf = 0;
    const tick = () => {
      const el = findTarget(step.target);
      if (el) {
        const r = el.getBoundingClientRect();
        setRect((old) => (old && old.top === r.top && old.left === r.left && old.width === r.width
          && old.height === r.height ? old : { top: r.top, left: r.left, width: r.width, height: r.height }));
      } else setRect(null);
      raf = requestAnimationFrame(tick);
    };
    const first = findTarget(step.target);
    first?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [step]);

  // bước chờ thao tác thật
  useEffect(() => {
    if (!step?.waitFor) return;
    const h = () => setTimeout(next, 350);
    window.addEventListener(`lawvn:${step.waitFor}`, h);
    return () => window.removeEventListener(`lawvn:${step.waitFor}`, h);
  }, [step, next]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(false); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  if (!step) return null;
  const pad = 6;
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  const below = rect ? rect.top + rect.height + 180 < vh : true;
  const cardTop = rect ? (below ? rect.top + rect.height + 14 : Math.max(12, rect.top - 14)) : vh / 2;
  const cardLeft = rect ? Math.min(Math.max(12, rect.left), vw - 352) : vw / 2 - 170;

  return (
    <div className="coach" role="dialog" aria-live="polite" aria-label={step.title}>
      {rect ? (() => {
        // bốn tấm phủ quanh vùng sáng (box-shadow khổng lồ hiển thị lỗi trên một số trình duyệt)
        const t = Math.max(0, rect.top - pad), l = Math.max(0, rect.left - pad);
        const b = rect.top + rect.height + pad, r = rect.left + rect.width + pad;
        return (
          <>
            <div className="coach-shade" style={{ top: 0, left: 0, right: 0, height: t }} />
            <div className="coach-shade" style={{ top: b, left: 0, right: 0, bottom: 0 }} />
            <div className="coach-shade" style={{ top: t, left: 0, width: l, height: b - t }} />
            <div className="coach-shade" style={{ top: t, left: r, right: 0, height: b - t }} />
            <div className="coach-spot" style={{ top: t, left: l, width: r - l, height: b - t }} />
          </>
        );
      })() : <div className="coach-dim" />}
      <div className={`coach-card ${rect && !below ? "above" : ""}`}
        style={{ top: cardTop, left: cardLeft, transform: rect && !below ? "translateY(-100%)" : undefined }}>
        <div className="coach-step">Bước {i + 1}/{steps.length}</div>
        <strong>{step.title}</strong>
        <p>{step.body}</p>
        {!rect && <p className="coach-hint">Phần này chưa hiện trên màn hình; làm bước trước hoặc bấm “Tiếp”.</p>}
        {step.waitFor && rect && <p className="coach-hint">👉 Bấm vào vùng được chiếu sáng để tiếp tục</p>}
        <div className="coach-actions">
          <button className="vi-btn" onClick={() => onClose(false)}>Bỏ qua</button>
          {i > 0 && <button className="vi-btn" onClick={() => setI(i - 1)}>Quay lại</button>}
          <button className="vi-btn primary" onClick={next}>{i + 1 >= steps.length ? "Xong" : "Tiếp"}</button>
        </div>
      </div>
    </div>
  );
}
