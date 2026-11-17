"use client";

/* Bài toán rút từ ghi âm / ghi chú nhóm (AU2): gợi ý cho mô hình, luật sư phân tích rồi
   duyệt hoặc bác bỏ. Chỉ bài `da_duyet` mới mang tên luật sư và được dùng làm tham khảo. */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { API_BASE, apiFetch } from "@/lib/api";
import { RequirePerm } from "@/lib/auth";

type Option = { name: string; pros: string; cons: string };
type Article = { node_id: string; display: string; score: number };
type Precedent = {
  number: string; title: string; status: string; url: string; similarity: number;
};
type Problem = {
  id: string; source_kind: string; upload_id: string | null; source_ts: string | null;
  filename: string | null; title: string; facts: string; legal_question: string;
  suggested_approach: string; options: Option[]; cited_articles: string[];
  uncertain_points: string[]; linked_articles: Article[]; linked_precedents: Precedent[];
  processed_by: string; status: string; lawyer_analysis: string | null;
  lawyer_verdict: string | null; approved_by: string | null; approved_at: string | null;
  created_at: string | null;
};

const TABS = [
  { key: "goi_y", label: "Gợi ý" },
  { key: "da_duyet", label: "Đã duyệt" },
  { key: "bac_bo", label: "Bác bỏ" },
];
const SOURCE: Record<string, string> = { audio: "Ghi âm", note: "Ghi chú nhóm" };
const PROCESSED: Record<string, string> = {
  local: "trong máy",
  dahl: "Dahl (bản đã che)",
};
const PREC_STATUS: Record<string, string> = {
  dang_ap_dung: "đang áp dụng",
  bi_huy_bo: "bị hủy bỏ",
  chua_ro: "chưa rõ",
};
const STATUS: Record<string, string> = {
  goi_y: "chờ luật sư",
  da_duyet: "đã duyệt",
  bac_bo: "bác bỏ",
};

export default function ProblemsPage() {
  return (
    <RequirePerm perm="review">
      <ProblemsInner />
    </RequirePerm>
  );
}

function ProblemsInner() {
  const [tab, setTab] = useState("goi_y");
  const [rows, setRows] = useState<Problem[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await apiFetch(`/api/problems?status=${tab}`);
      if (!r.ok) throw new Error(String(r.status));
      setRows(await r.json());
      setError("");
    } catch {
      setRows([]);
      setError("Không tải được danh sách bài toán.");
    }
  }, [tab]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="dash-shell">
      <div className="dash-header">
        <Link href="/" className="dash-back">← Chat</Link>
        <span className="dash-title">Bài toán</span>
        <Link href="/upload" className="dash-graph-btn">Tải ghi âm</Link>
      </div>

      <div className="dash-body">
        <p className="bt-note">
          Gợi ý từ ghi âm và nhóm — chưa được luật sư phân tích.
        </p>

        <div className="bt-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`bt-tab${tab === t.key ? " active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {error && <div className="bt-error">{error}</div>}
        {rows.length === 0 && !error ? (
          <div className="dash-empty">Chưa có bài toán nào ở mục này.</div>
        ) : (
          rows.map((p) => <ProblemCard key={p.id} problem={p} onSaved={load} />)
        )}
      </div>
    </div>
  );
}

function ProblemCard({ problem: p, onSaved }: { problem: Problem; onSaved: () => void }) {
  const [analysis, setAnalysis] = useState(p.lawyer_analysis ?? "");
  const [verdict, setVerdict] = useState(p.lawyer_verdict ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function act(status: "da_duyet" | "bac_bo") {
    setBusy(true);
    setError("");
    try {
      const r = await apiFetch(`/api/problems/${p.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, lawyer_analysis: analysis, lawyer_verdict: verdict }),
      });
      if (!r.ok) throw new Error(String(r.status));
      onSaved();
    } catch {
      setError("Không lưu được quyết định.");
    } finally {
      setBusy(false);
    }
  }

  const source = SOURCE[p.source_kind] ?? p.source_kind;
  const place = p.filename || p.upload_id || "";
  const stamp = p.source_ts ? ` · ${p.source_ts}` : "";

  return (
    <div className="bt-card">
      <div className="bt-card-head">
        <div className="bt-title">{p.title}</div>
        <span className={`bt-status ${p.status}`}>{STATUS[p.status] ?? p.status}</span>
      </div>
      <div className="bt-meta">
        {source}{place ? `: ${place}` : ""}{stamp} · Xử lý bởi: {PROCESSED[p.processed_by] ?? p.processed_by}
        {p.source_kind === "audio" && (
          <>
            {" · "}
            <Link href={`/upload`} className="bt-link">tệp gốc</Link>
          </>
        )}
      </div>

      <div className="bt-row"><span className="bt-label">Tình tiết</span><span>{p.facts}</span></div>
      <div className="bt-row"><span className="bt-label">Câu hỏi pháp lý</span><span>{p.legal_question}</span></div>
      {p.suggested_approach && (
        <div className="bt-row">
          <span className="bt-label">Hướng người nói khuyến nghị</span>
          <span>{p.suggested_approach}</span>
        </div>
      )}

      {p.options.length > 0 && (
        <table className="bt-options">
          <thead>
            <tr><th>Phương án</th><th>Ưu điểm</th><th>Nhược điểm</th></tr>
          </thead>
          <tbody>
            {p.options.map((o, i) => (
              <tr key={i}>
                <td>{o.name}</td>
                <td>{o.pros || "—"}</td>
                <td>{o.cons || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {p.cited_articles.length > 0 && (
        <div className="bt-row">
          <span className="bt-label">Người nói đã nêu</span>
          <span>{p.cited_articles.join("; ")}</span>
        </div>
      )}
      {p.uncertain_points.length > 0 && (
        <div className="bt-row">
          <span className="bt-label">Cần luật sư xác nhận</span>
          <span>{p.uncertain_points.join("; ")}</span>
        </div>
      )}

      <div className="bt-links">
        {p.linked_articles.length > 0 && (
          <div className="bt-link-group">
            <span className="bt-label">Điều luật liên quan</span>
            {p.linked_articles.map((a) => (
              <a
                key={a.node_id}
                className="bt-link"
                href={`${API_BASE}/api/law/${encodeURIComponent(a.node_id)}`}
                target="_blank"
                rel="noreferrer"
                title={`điểm khớp ${a.score}`}
              >
                {a.display || a.node_id}
              </a>
            ))}
          </div>
        )}
        {p.linked_precedents.length > 0 && (
          <div className="bt-link-group">
            <span className="bt-label">Án lệ có thể liên quan</span>
            {p.linked_precedents.map((a) => (
              <a
                key={`${a.number}-${a.url}`}
                className="bt-link"
                href={a.url || "#"}
                target="_blank"
                rel="noreferrer"
              >
                Án lệ {a.number}
                <span className={`bt-prec ${a.status}`}>
                  {PREC_STATUS[a.status] ?? a.status}
                </span>
                <span className="bt-sim">{Math.round(a.similarity * 100)}%</span>
                {" "}{a.title}
              </a>
            ))}
          </div>
        )}
      </div>

      <div className="bt-lawyer">
        <div className="bt-lawyer-head">
          Phân tích của luật sư
          {p.approved_by && (
            <span className="bt-approved">
              {p.approved_by}
              {p.approved_at ? ` · ${p.approved_at.slice(0, 10)}` : ""}
            </span>
          )}
        </div>
        <textarea
          className="bt-textarea"
          value={analysis}
          placeholder="Phân tích pháp lý của luật sư"
          onChange={(e) => setAnalysis(e.target.value)}
        />
        <textarea
          className="bt-textarea"
          value={verdict}
          placeholder="Kết luận / hướng xử lý"
          onChange={(e) => setVerdict(e.target.value)}
        />
        {error && <div className="bt-error">{error}</div>}
        <div className="bt-actions">
          <button className="bt-btn ok" disabled={busy} onClick={() => act("da_duyet")}>
            Duyệt
          </button>
          <button className="bt-btn bad" disabled={busy} onClick={() => act("bac_bo")}>
            Bác bỏ
          </button>
        </div>
      </div>
    </div>
  );
}
