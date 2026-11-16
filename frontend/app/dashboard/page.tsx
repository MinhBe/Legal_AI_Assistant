"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const STORE_KEY = "llv_conversations";

type Escalation = {
  id: string; question: string; status: string;
  created_at: string; thread_id?: string; reply?: string;
};
type HealthData = {
  status: string; db: boolean; documents: number; nodes: number;
  data_loaded: boolean; llm: string[] | Record<string, unknown> | string;
};
type Convo = { id: string; title: string; messages: { role: string }[] };

/* Người duyệt (human-in-the-loop): viết câu trả lời rồi duyệt, hoặc từ chối kèm lý do.
   Kết quả hiện lại trong thẻ phê duyệt của người hỏi. */
function EscalationReview({ esc, onDone }: { esc: Escalation; onDone: (e: Escalation) => void }) {
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function decide(status: "approved" | "denied") {
    if (status === "approved" && !reply.trim()) { setErr("Viết câu trả lời trước khi duyệt."); return; }
    setBusy(true); setErr("");
    try {
      const r = await fetch(`${API_BASE}/api/escalations/${esc.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, reply }),
      });
      if (!r.ok) throw new Error(String(r.status));
      onDone(await r.json());
    } catch { setErr("Không gửi được, thử lại."); }
    finally { setBusy(false); }
  }

  return (
    <div className="esc-review">
      <textarea className="esc-reply" rows={3} value={reply} disabled={busy}
        placeholder="Câu trả lời của chuyên gia (bắt buộc khi duyệt) hoặc lý do từ chối…"
        onChange={(e) => setReply(e.target.value)} />
      <div className="esc-actions">
        <button className="btn-approve" disabled={busy} onClick={() => decide("approved")}>Duyệt &amp; gửi trả lời</button>
        <button className="btn-deny" disabled={busy} onClick={() => decide("denied")}>Từ chối</button>
        {err && <span className="dash-err">{err}</span>}
      </div>
    </div>
  );
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return "vừa xong";
  if (m < 60) return `${m} phút trước`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} giờ trước`;
  return `${Math.floor(h / 24)} ngày trước`;
}

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [convos, setConvos] = useState<Convo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Load conversations from localStorage
    try {
      const raw = localStorage.getItem(STORE_KEY);
      setConvos(raw ? JSON.parse(raw) : []);
    } catch { setConvos([]); }

    // Fetch health + escalations in parallel
    Promise.all([
      fetch(`${API_BASE}/health`).then((r) => r.json()).catch(() => null),
      fetch(`${API_BASE}/api/escalations`).then((r) => r.json()).catch(() => []),
    ]).then(([h, e]) => {
      setHealth(h);
      setEscalations(Array.isArray(e) ? e : []);
      setLoading(false);
    });
  }, []);

  const pending = escalations.filter((e) => e.status === "pending").length;
  const totalMsgs = convos.reduce((s, c) => s + c.messages.length, 0);

  return (
    <div className="dash-shell">
      <div className="dash-header">
        <Link href="/" className="dash-back">← Chat</Link>
        <span className="dash-title">Dashboard</span>
        <Link href="/review" className="dash-graph-btn">Bàn duyệt luật sư →</Link>
        <Link href="/graph" className="dash-graph-btn">Knowledge Graph</Link>
      </div>

      <div className="dash-body">
        {/* Stat cards */}
        <div className="dash-stats">
          <div className="stat-card">
            <div className="stat-num">{convos.length}</div>
            <div className="stat-label">Cuộc hội thoại đã lưu</div>
          </div>
          <div className="stat-card">
            <div className="stat-num">{totalMsgs}</div>
            <div className="stat-label">Tổng tin nhắn</div>
          </div>
          <div className="stat-card">
            <div className="stat-num">{health?.nodes ?? "—"}</div>
            <div className="stat-label">Nodes trong kho luật</div>
          </div>
          <div className="stat-card">
            <div className={`stat-num ${pending > 0 ? "warn" : ""}`}>{pending}</div>
            <div className="stat-label">Yêu cầu chờ phê duyệt</div>
          </div>
        </div>

        <div className="dash-grid">
          {/* System health */}
          <div className="dash-card">
            <div className="dash-card-title">Trạng thái hệ thống</div>
            {loading ? (
              <div className="dash-loading">Đang tải…</div>
            ) : health ? (
              <table className="dash-table">
                <tbody>
                  <tr><td>API</td><td><span className={`badge ${health.status === "ok" ? "ok" : "err"}`}>{health.status}</span></td></tr>
                  <tr><td>Database</td><td><span className={`badge ${health.db ? "ok" : "err"}`}>{health.db ? "connected" : "error"}</span></td></tr>
                  <tr><td>Văn bản</td><td>{health.documents} tài liệu</td></tr>
                  <tr><td>Nodes</td><td>{health.nodes.toLocaleString()}</td></tr>
                  <tr><td>LLM providers</td><td>{Array.isArray(health.llm) ? health.llm.join(", ") : (health.llm ? JSON.stringify(health.llm) : "—")}</td></tr>
                </tbody>
              </table>
            ) : (
              <div className="dash-err">Không kết nối được API</div>
            )}
          </div>

          {/* Escalations */}
          <div className="dash-card">
            <div className="dash-card-title">Yêu cầu phê duyệt ({escalations.length})</div>
            {escalations.length === 0 ? (
              <div className="dash-empty">Chưa có yêu cầu nào.</div>
            ) : (
              <div className="esc-list">
                {escalations.slice(0, 10).map((e) => (
                  <div key={e.id} className="esc-item">
                    <div className="esc-row">
                      <span className={`badge ${e.status === "pending" ? "warn" : e.status === "approved" ? "ok" : "err"}`}>
                        {e.status}
                      </span>
                      <span className="esc-q">{e.question}</span>
                      <span className="esc-time">{timeAgo(e.created_at)}</span>
                    </div>
                    {e.status === "pending" ? (
                      <EscalationReview esc={e}
                        onDone={(u) => setEscalations((all) => all.map((x) => (x.id === u.id ? u : x)))} />
                    ) : e.reply ? (
                      <div className="esc-answer">{e.reply}</div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recent conversations */}
          <div className="dash-card span2">
            <div className="dash-card-title">Cuộc hội thoại gần đây</div>
            {convos.length === 0 ? (
              <div className="dash-empty">Chưa có cuộc hội thoại nào.</div>
            ) : (
              <div className="convo-list">
                {convos.slice(0, 20).map((c) => (
                  <Link key={c.id} href={`/?t=${c.id}`} className="convo-row">
                    <span className="convo-title">{c.title}</span>
                    <span className="convo-meta">{c.messages.length} tin · #{c.id.slice(0, 8)}</span>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
