"use client";

/* Nút "?" trên thanh đầu: Bảng tra cứu (tìm kiếm, theo vai trò) và Xem lại hướng dẫn.
   Tự mở hướng dẫn lần đầu cho từng nhóm vai trò (nhớ trong trình duyệt). */
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import Coach from "@/components/help/Coach";
import { useAuth } from "@/lib/auth";
import { HELP, roleGroup, TOURS } from "@/lib/help/content";

const ROLE_LABEL = { guest: "Khách", user: "Người dùng", admin: "Quản trị" } as const;
const seenKey = (g: string) => `lawvn_tour_seen_${g}`;

export default function HelpMenu() {
  const { user, ready } = useAuth();
  const group = roleGroup(user.role);
  const [menu, setMenu] = useState(false);
  const [panel, setPanel] = useState(false);
  const [tour, setTour] = useState<{ at: number } | null>(null);
  const [query, setQuery] = useState("");
  const steps = TOURS[group];

  useEffect(() => {
    if (!ready) return;
    try {
      if (!localStorage.getItem(seenKey(group))) setTour({ at: 0 });
    } catch { /* storage bị chặn: không tự mở */ }
  }, [ready, group]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === "?" && !["INPUT", "TEXTAREA"].includes(t.tagName)) { setPanel(true); setMenu(false); }
      if (e.key === "Escape") { setPanel(false); setMenu(false); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  const entries = useMemo(() => {
    const q = query.trim().toLowerCase();
    return HELP.filter((h) => h.roles.includes(group))
      .filter((h) => !q || `${h.q} ${h.a} ${h.topic}`.toLowerCase().includes(q));
  }, [group, query]);
  const topics = [...new Set(entries.map((e) => e.topic))];

  const showMe = (stepId: string) => {
    const at = steps.findIndex((s) => s.id === stepId);
    if (at < 0) return;
    setPanel(false);
    setTour({ at });
  };
  const endTour = () => {
    try { localStorage.setItem(seenKey(group), "1"); } catch { /* bỏ qua */ }
    setTour(null);
  };

  return (
    <>
      <div className="help-wrap">
        <button className="help-btn" aria-label="Trợ giúp" title="Trợ giúp (phím ?)" onClick={() => setMenu((v) => !v)}>?</button>
        {menu && (
          <div className="help-menu" role="menu">
            <button role="menuitem" onClick={() => { setPanel(true); setMenu(false); }}>📖 Bảng tra cứu</button>
            <button role="menuitem" onClick={() => { setTour({ at: 0 }); setMenu(false); }}>▶ Xem lại hướng dẫn</button>
          </div>
        )}
      </div>

      {panel && createPortal(
        <div className="vi-backdrop" onClick={() => setPanel(false)}>
          <aside className="help-panel" onClick={(e) => e.stopPropagation()} aria-label="Bảng tra cứu">
            <header className="vi-head">
              <strong>Bảng tra cứu · {ROLE_LABEL[group]}</strong>
              <button className="icon-btn" onClick={() => setPanel(false)} aria-label="Đóng">✕</button>
            </header>
            <div className="vi-body">
              <input className="vi-repl help-search" autoFocus placeholder="Tìm: ghi âm, làm mờ, trích dẫn, duyệt văn bản…"
                value={query} onChange={(e) => setQuery(e.target.value)} />
              {topics.map((t) => (
                <section key={t}>
                  <h4 className="help-topic">{t}</h4>
                  {entries.filter((e) => e.topic === t).map((e) => (
                    <details key={e.id} className="help-entry">
                      <summary>{e.q}</summary>
                      <p>{e.a}</p>
                      {e.tourStep && steps.some((s) => s.id === e.tourStep) && (
                        <button className="vi-btn" onClick={() => showMe(e.tourStep!)}>👉 Chỉ cho tôi</button>
                      )}
                    </details>
                  ))}
                </section>
              ))}
              {entries.length === 0 && <p className="vi-note">Không thấy mục nào khớp.</p>}
            </div>
          </aside>
        </div>, document.body,
      )}

      {/* portal: thanh đầu có backdrop-filter, phần tử fixed bên trong sẽ bị neo theo thanh đầu */}
      {tour && createPortal(<Coach key={tour.at} steps={steps} startAt={tour.at} onClose={endTour} />, document.body)}
    </>
  );
}
