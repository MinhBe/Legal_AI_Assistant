"use client";

/* Tin pháp luật mới (LI1): danh sách văn bản/án lệ mới do luồng nền quét về, phần tích
   bằng Dahl và định tuyến cho luật sư. Chỉ admin/dev xem được (quyền "review"). */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { API_BASE, apiFetch } from "@/lib/api";
import { RequirePerm } from "@/lib/auth";

type SourceStatus = { status: string; found: number; new: number };
type Run = {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  trigger: string;
  per_source: Record<string, SourceStatus>;
  error: string | null;
};
type Analysis = {
  relevant_labor: boolean;
  topic: string;
  summary: string;
  what_changes: string;
  amends: string[];
  replaces: string[];
  affected_nodes: string[];
  effective_date: string | null;
  impact: "cao" | "trung bình" | "thấp";
  impact_reason: string;
  routing: { queue: string; action: string; kg_updates: string[] };
  needs_full_text: boolean;
  confidence: number;
};
type Item = {
  id: string;
  source: string;
  url: string;
  title: string;
  number: string;
  kind: string;
  category: string;
  listed_date: string | null;
  first_seen: string | null;
  labor_hint: boolean;
  in_corpus: boolean;
  status: string;
  analysis: Analysis | null;
  error: string | null;
  reviewed_by: string | null;
};
type Tab = "queue" | "all" | "approved" | "ignored";

const TABS: { key: Tab; label: string }[] = [
  { key: "queue", label: "Cần xem" },
  { key: "all", label: "Tất cả" },
  { key: "approved", label: "Đã duyệt" },
  { key: "ignored", label: "Bỏ qua" },
];
const SOURCE_STATUS: Record<string, string> = {
  ok: "OK", blocked: "Bị chặn", needs_browser: "Cần trình duyệt", error: "Lỗi",
};
const ITEM_STATUS: Record<string, string> = {
  new: "Chờ phân tích", analysed: "Đã phân tích", skipped: "Không liên quan",
  approved: "Đã duyệt", ignored: "Bỏ qua", blocked: "Bị chặn",
};
const IMPACT_CLASS: Record<string, string> = {
  cao: "intel-impact-cao", "trung bình": "intel-impact-tb", "thấp": "intel-impact-thap",
};

function day(iso: string | null): string {
  if (!iso) return "chưa rõ";
  return new Date(iso).toLocaleString("vi-VN", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function sourceChip(name: string, info: SourceStatus) {
  const text = info.status === "ok" ? `OK ${info.new} mới` : SOURCE_STATUS[info.status] ?? info.status;
  return (
    <span className={`intel-chip intel-chip-${info.status}`} key={name} title={`${info.found} văn bản trên trang`}>
      {name}: {text}
    </span>
  );
}

export default function TinMoiPage() {
  return (
    <RequirePerm perm="review">
      <TinMoiPageInner />
    </RequirePerm>
  );
}

function TinMoiPageInner() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [tab, setTab] = useState<Tab>("queue");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const [r, i] = await Promise.all([
      apiFetch("/api/intel/runs?limit=5").then((res) => res.json()).catch(() => []),
      apiFetch("/api/intel/items").then((res) => res.json()).catch(() => []),
    ]);
    setRuns(Array.isArray(r) ? r : []);
    setItems(Array.isArray(i) ? i : []);
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Đang quét thì hỏi lại mỗi 5 giây để thanh trạng thái tự cập nhật.
  const running = Boolean(runs[0] && !runs[0].finished_at);
  useEffect(() => {
    const timer = setInterval(() => {
      if (running) void load();
    }, 5000);
    return () => clearInterval(timer);
  }, [running, load]);

  async function scan() {
    setBusy(true); setErr("");
    try {
      const res = await apiFetch("/api/intel/scan", { method: "POST" });
      if (!res.ok) throw new Error(res.status === 409 ? "Đang có vòng quét chạy" : String(res.status));
      await load();
    } catch (e) { setErr(e instanceof Error ? e.message : "Không quét được"); }
    finally { setBusy(false); }
  }

  async function act(id: string, action: "approve" | "ignore" | "analyse") {
    setBusy(true); setErr("");
    try {
      const res = await apiFetch(`/api/intel/items/${id}/${action}`, { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
      await load();
    } catch (e) { setErr(e instanceof Error ? e.message : "Không gửi được"); }
    finally { setBusy(false); }
  }

  const last = runs[0];
  const shown = items.filter((i) => {
    if (tab === "queue") return i.status === "analysed" && i.labor_hint;
    if (tab === "approved") return i.status === "approved";
    if (tab === "ignored") return i.status === "ignored";
    return true;
  });
  // "Cần xem": ảnh hưởng cao trước, rồi độ tin cậy; các tab khác giữ thứ tự mới nhất trước
  if (tab === "queue") {
    const rank: Record<string, number> = { cao: 0, "trung bình": 1, thấp: 2 };
    const info = (i: Item) => {
      const a = (typeof i.analysis === "string" ? JSON.parse(i.analysis || "{}") : i.analysis) || {};
      return { r: rank[a.impact as string] ?? 3, c: Number(a.confidence) || 0 };
    };
    shown.sort((x, y) => info(x).r - info(y).r || info(y).c - info(x).c);
  }

  return (
    <div className="intel-shell">
      <header className="intel-header">
        <Link href="/" className="intel-back">← Trang chủ</Link>
        <h1 className="intel-title-main">Tin pháp luật mới</h1>
        <span className="intel-last">
          {last ? `Lượt gần nhất: ${day(last.started_at)} (${last.trigger === "manual" ? "quét tay" : "theo lịch"})` : "Chưa có lượt quét nào"}
        </span>
        <button className="intel-scan" onClick={scan} disabled={busy || running}>
          {running ? "Đang quét…" : "Quét ngay"}
        </button>
      </header>

      <div className="intel-strip">
        {last
          ? Object.entries(last.per_source).map(([name, info]) => sourceChip(name, info))
          : <span className="intel-empty">Bấm “Quét ngay” để lấy danh sách văn bản mới.</span>}
        {last?.error && <span className="intel-err">{last.error}</span>}
        {err && <span className="intel-err">{err}</span>}
      </div>

      <div className="intel-tabs">
        {TABS.map((t) => (
          <button key={t.key} className={`intel-tab ${tab === t.key ? "on" : ""}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
        <span className="intel-count">{shown.length} tin</span>
      </div>

      <div className="intel-body">
        {loading && <div className="intel-empty">Đang tải…</div>}
        {!loading && shown.length === 0 && <div className="intel-empty">Không có tin nào ở mục này.</div>}
        {shown.map((item) => (
          <article className="intel-card" key={item.id}>
            <div className="intel-card-top">
              <a className="intel-item-title" href={item.url} target="_blank" rel="noreferrer">
                {item.title}
              </a>
              {item.analysis && (
                <span className={`intel-impact ${IMPACT_CLASS[item.analysis.impact] ?? ""}`}>
                  Ảnh hưởng: {item.analysis.impact}
                </span>
              )}
            </div>

            <div className="intel-meta">
              <span>{item.number || "không rõ số hiệu"}</span>
              <span>{item.source}</span>
              {item.kind && <span>{item.kind}</span>}
              <span>Đăng: {item.listed_date ?? "không hiển thị"}</span>
              <span className={`intel-status intel-status-${item.status}`}>{ITEM_STATUS[item.status] ?? item.status}</span>
              {item.in_corpus && <span className="intel-flag">đã có trong kho</span>}
            </div>

            {item.analysis ? (
              <div className="intel-analysis">
                <p className="intel-summary">{item.analysis.summary}</p>
                <div className="intel-field"><b>Thay đổi gì:</b> {item.analysis.what_changes}</div>
                {(item.analysis.amends.length > 0 || item.analysis.replaces.length > 0) && (
                  <div className="intel-chips">
                    {item.analysis.amends.map((n) => <span className="intel-chip" key={`a-${n}`}>sửa: {n}</span>)}
                    {item.analysis.replaces.map((n) => <span className="intel-chip" key={`r-${n}`}>thay: {n}</span>)}
                  </div>
                )}
                {item.analysis.affected_nodes.length > 0 && (
                  <div className="intel-chips">
                    {item.analysis.affected_nodes.map((node) => (
                      <a className="intel-chip intel-node" key={node} href={`${API_BASE}/api/law/${node}`} target="_blank" rel="noreferrer">
                        {node}
                      </a>
                    ))}
                  </div>
                )}
                <div className="intel-field">
                  <b>Hiệu lực:</b> {item.analysis.effective_date ?? "chưa rõ"} · <b>Lý do:</b>{" "}
                  {item.analysis.impact_reason}
                </div>
                <div className="intel-field">
                  <b>Định tuyến:</b> {item.analysis.routing.queue} · {item.analysis.routing.action}
                  {item.analysis.routing.kg_updates.length > 0 && ` · kho: ${item.analysis.routing.kg_updates.join(", ")}`}
                  {" · "}
                  <b>Tin cậy:</b> {Math.round(item.analysis.confidence * 100)}%
                </div>
                {item.analysis.needs_full_text && (
                  <div className="intel-warn">Tóm tắt chỉ từ tiêu đề — cần toàn văn</div>
                )}
              </div>
            ) : (
              <div className="intel-field">
                {item.error ? `Chưa phân tích được: ${item.error}` : "Chưa có phân tích."}
              </div>
            )}

            {item.status === "approved" && (
              <div className="intel-upload-hint">
                Đã duyệt. Tải toàn văn văn bản về máy rồi nạp ở <Link href="/upload">/upload</Link> để đưa vào kho
                (không tự tải trang văn bản: có thể bị chặn hoặc vướng bản quyền).
              </div>
            )}

            <div className="intel-actions">
              <button className="intel-btn intel-btn-ok" disabled={busy} onClick={() => act(item.id, "approve")}>Duyệt</button>
              <button className="intel-btn" disabled={busy} onClick={() => act(item.id, "ignore")}>Bỏ qua</button>
              <button className="intel-btn" disabled={busy} onClick={() => act(item.id, "analyse")}>Phân tích lại</button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
