"use client";

/* Thu thập dữ liệu (admin): các nguồn web scraping theo tab, trạng thái robots.txt, lần chạy gần
   nhất, số mục, lỗi, độ tươi, và "Chạy thử 5 mục" xem từng bước. Danh sách nguồn ở backend
   app/collect/registry.py: thêm nguồn = thêm một mục, trang tự hiện tab mới. */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api";
import { RequirePerm } from "@/lib/auth";

type Source = {
  id: string; tab: string; name: string; home: string; list_url: string; use: string; why: string;
  script: string; pace_s: number; tags: string[];
  items?: number; errors?: number; last_at?: string; fresh_days?: number;
};
type Step = { step: string; ok: boolean; detail: string; ms: number };
type Probe = { source: string; steps: Step[]; items: { url: string; title?: string; http?: number }[] };

const USE_BADGE: Record<string, string> = { "dùng": "ok", "tìm tiếp": "wip", "không dùng": "no" };

function Inner() {
  const [sources, setSources] = useState<Source[]>([]);
  const [tab, setTab] = useState("");
  const [probe, setProbe] = useState<Record<string, Probe | "running">>({});
  const [err, setErr] = useState("");

  useEffect(() => {
    apiFetch("/api/collect/sources").then(async (r) => {
      if (!r.ok) { setErr(`Lỗi ${r.status}`); return; }
      const b = await r.json();
      setSources(b.sources);
      setTab(b.sources[0]?.tab || "");
    }).catch(() => setErr("Mất kết nối"));
  }, []);

  const tabs = useMemo(() => [...new Set(sources.map((s) => s.tab))], [sources]);

  const run = async (id: string) => {
    setProbe((p) => ({ ...p, [id]: "running" }));
    const r = await apiFetch(`/api/collect/sources/${id}/probe`, { method: "POST" }).catch(() => null);
    const b = r?.ok ? await r.json() : { source: id, steps: [{ step: "Lỗi", ok: false, detail: `HTTP ${r?.status ?? "?"}`, ms: 0 }], items: [] };
    setProbe((p) => ({ ...p, [id]: b }));
  };

  return (
    <main className="collect-page">
      <header className="collect-head">
        <Link href="/" className="auth-link">← Trợ lý</Link>
        <h1>Thu thập dữ liệu</h1>
        <p className="vi-note">
          Mọi nguồn đều tôn trọng robots.txt, giãn cách ≥ 5 giây, ghi rõ User-Agent, không vượt CAPTCHA,
          không đăng nhập hộ. Dữ liệu mới đi qua bước che PII và nằm ở /upload chờ duyệt trước khi được dùng.
        </p>
      </header>
      {err && <p className="vi-error">{err}</p>}
      <nav className="collect-tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t} role="tab" aria-selected={t === tab} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
            {t} <small>({sources.filter((s) => s.tab === t).length})</small>
          </button>
        ))}
      </nav>
      <div className="collect-grid">
        {sources.filter((s) => s.tab === tab).map((s) => {
          const p = probe[s.id];
          return (
            <section key={s.id} className="collect-card">
              <div className="collect-card-head">
                <strong>{s.name}</strong>
                <span className={`collect-use ${USE_BADGE[s.use] || ""}`}>{s.use}</span>
              </div>
              <a href={s.home} target="_blank" rel="noreferrer" className="vi-note">{s.home}</a>
              <p className="collect-why">{s.why}</p>
              <dl className="collect-stats">
                <div><dt>Mục đã lấy</dt><dd>{s.items ?? "—"}</dd></div>
                <div><dt>Lỗi</dt><dd>{s.errors ?? "—"}</dd></div>
                <div><dt>Lần chạy gần nhất</dt><dd>{s.last_at ? new Date(s.last_at).toLocaleString("vi-VN") : "—"}</dd></div>
                <div><dt>Độ tươi</dt><dd>{s.fresh_days != null ? `${s.fresh_days} ngày` : "—"}</dd></div>
              </dl>
              <div className="collect-tags">
                {s.tags.map((t) => <span key={t} className="chip">{t}</span>)}
                <span className="vi-note">Công cụ: <code>{s.script}</code></span>
              </div>
              {s.use !== "không dùng" && s.list_url && (
                <button className="vi-btn" disabled={p === "running"} onClick={() => run(s.id)}>
                  {p === "running" ? "Đang chạy thử (giãn cách 5 giây)…" : "▶ Chạy thử 5 mục"}
                </button>
              )}
              {p && p !== "running" && (
                <ol className="collect-steps">
                  {p.steps.map((st, i) => (
                    <li key={i} className={st.ok ? "ok" : "fail"}>
                      <span>{st.ok ? "✔" : "✖"} {st.step}</span>
                      <small>{st.detail}{st.ms ? ` · ${st.ms} ms` : ""}</small>
                    </li>
                  ))}
                  {p.items.length > 0 && (
                    <li className="ok"><span>Mục tìm thấy</span>
                      <small>{p.items.map((it) => it.title || it.url).slice(0, 5).join(" · ")}</small></li>
                  )}
                </ol>
              )}
            </section>
          );
        })}
      </div>
    </main>
  );
}

export default function CollectPage() {
  return <RequirePerm perm="upload"><Inner /></RequirePerm>;
}
