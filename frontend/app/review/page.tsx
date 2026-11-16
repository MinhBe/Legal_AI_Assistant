"use client";

/* Bàn duyệt luật sư (R2, design §9.2–9.3): gói ca bên phải, hàng đợi bên trái,
   bốn hành động kèm diff và nhãn lỗi. */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { RequirePerm } from "@/lib/auth";

import { TimeFrameBox } from "@/components/chat/AnswerParts";
import type { TimeFrame, Verifier } from "@/lib/chat/types";


type RiskReason = { code: string; weight: number | "inf"; message: string };
type CaseRow = {
  id: string; created_at: string; question: string; risk_score: string;
  reasons: RiskReason[]; status: string; source: string; answer_id: string | null;
  thread_id?: string | null; due_at: string | null; overdue: boolean;
};
type Provision = { node_id: string; doc_id: string | null; heading: string | null; text: string };
type Pkg = CaseRow & {
  draft: string | null;
  timeframe: TimeFrame | null;
  verifier: Verifier | null;
  provisions: Provision[];
  prompt_version: string | null;
  model: string | null;
  diff: string | null;
  reviewer_text: string | null;
  error_labels: string[];
  reply: string | null;
};
type Stats = {
  total: number; by_status: Record<string, number>;
  by_label: Record<string, number>; approved_rate: number | null;
  traps?: { total: number; reviewed: number; caught: number; catch_rate: number | null };
};
type Duty = { on_duty: boolean; lawyer: string; backup: string };
type Autonomy = { case_type: string; level: number; reason: string | null };
type Action = "approve" | "light_edit" | "heavy_edit" | "reject";
type Filter = "pending" | "done" | "all";

/* Ca bẫy (R3) dùng nhãn như ca tự động: hàng đợi không được lộ ca nào là bẫy. */
const SOURCE_LABEL: Record<string, string> = {
  auto: "Tự động", user: "Người dùng gửi", trap: "Tự động",
};
const CASE_TYPE_LABEL: Record<string, string> = {
  cham_dut: "Chấm dứt", tien_luong: "Tiền lương", nghi_ngoi: "Nghỉ ngơi",
  ky_luat: "Kỷ luật", hop_dong: "Hợp đồng", khac: "Khác",
};
const STATUS_LABEL: Record<string, string> = {
  pending: "Chờ duyệt", approved: "Duyệt thẳng", light_edit: "Sửa nhẹ",
  heavy_edit: "Sửa nhiều", rejected: "Từ chối",
};

function timeAgo(iso: string): string {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "vừa xong";
  if (m < 60) return `${m} phút trước`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} giờ trước` : `${Math.floor(h / 24)} ngày trước`;
}

/* Hạn duyệt (R7): "Hạn 10:00 05/05". */
function dueLabel(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `Hạn ${d.toLocaleString("vi-VN", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  })}`;
}

function Diff({ text }: { text: string }) {
  return (
    <pre className="rv-diff">
      {text.split("\n").map((line, i) => {
        const cls = line.startsWith("+++") || line.startsWith("---") ? "rv-diff-head"
          : line.startsWith("+") ? "rv-diff-add"
            : line.startsWith("-") ? "rv-diff-del"
              : line.startsWith("@@") ? "rv-diff-hunk" : "";
        return <div className={cls} key={i}>{line || " "}</div>;
      })}
    </pre>
  );
}

export default function ReviewPage() {
  return (
    <RequirePerm perm="review">
      <ReviewPageInner />
    </RequirePerm>
  );
}

function ReviewPageInner() {
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [filter, setFilter] = useState<Filter>("pending");
  const [openId, setOpenId] = useState<string | null>(null);
  const [pkg, setPkg] = useState<Pkg | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [labelNames, setLabelNames] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [extra, setExtra] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [duty, setDuty] = useState<Duty | null>(null);
  const [levels, setLevels] = useState<Autonomy[]>([]);

  const load = useCallback(async () => {
    const [c, s, l, d, a] = await Promise.all([
      apiFetch(`/api/review/cases?status=all`).then((r) => r.json()).catch(() => []),
      apiFetch(`/api/review/stats`).then((r) => r.json()).catch(() => null),
      apiFetch(`/api/review/labels`).then((r) => r.json()).catch(() => ({})),
      apiFetch(`/api/review/duty`).then((r) => r.json()).catch(() => null),
      apiFetch(`/api/review/autonomy`).then((r) => r.json()).catch(() => []),
    ]);
    const rows: CaseRow[] = Array.isArray(c) ? c : [];
    rows.sort((a, b) => Number(b.status === "pending") - Number(a.status === "pending"));
    setCases(rows);
    setStats(s as Stats | null);
    setLabelNames(l && typeof l === "object" ? (l as Record<string, string>) : {});
    setDuty(d as Duty | null);
    setLevels(Array.isArray(a) ? (a as Autonomy[]) : []);
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!openId && cases.length > 0) setOpenId(cases[0].id);
  }, [cases, openId]);

  useEffect(() => {
    if (!openId) { setPkg(null); return; }
    let alive = true;
    apiFetch(`/api/review/cases/${openId}/package`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((p: Pkg) => {
        if (!alive) return;
        setPkg(p);
        setDraft(p.draft ?? "");
        setChosen([]);
        setReason("");
        setExtra(null);
        setErr("");
      })
      .catch(() => { if (alive) setErr("Không tải được gói ca."); });
    return () => { alive = false; };
  }, [openId]);

  async function act(action: Action) {
    if (!pkg) return;
    setBusy(true);
    setErr("");
    try {
      const r = await apiFetch(`/api/review/cases/${pkg.id}/act`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, text: draft, labels: chosen, reason }),
      });
      const body = await r.json();
      if (!r.ok) {
        setErr(typeof body?.detail === "string" ? body.detail : "Không gửi được hành động.");
        return;
      }
      const fresh: Pkg = await apiFetch(`/api/review/cases/${pkg.id}/package`).then((x) => x.json());
      setPkg(fresh);
      setDraft(fresh.draft ?? "");
      setExtra(null);
      setFilter("done");
      await load();
    } catch {
      setErr("Không gửi được hành động.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleDuty() {
    if (!duty) return;
    const r = await apiFetch(`/api/review/duty`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on_duty: !duty.on_duty }),
    });
    if (r.ok) setDuty((await r.json()) as Duty);
    await load();
  }

  async function changeLevel(ct: string, level: number) {
    const r = await apiFetch(`/api/review/autonomy/${ct}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level, reason: "" }),
    });
    if (r.ok) await load();
  }

  const shown = cases.filter((c) =>
    filter === "all" ? true : filter === "pending" ? c.status === "pending" : c.status !== "pending");

  const pending = stats?.by_status?.pending ?? 0;
  const rate = stats?.approved_rate == null ? "—" : `${Math.round(stats.approved_rate * 100)}%`;
  const top = Object.entries(stats?.by_label ?? {})
    .sort((a, b) => b[1] - a[1]).slice(0, 3)
    .map(([key, n]) => `${labelNames[key] ?? key} ${n}`).join(" · ") || "—";
  const trapRate = stats?.traps?.catch_rate == null
    ? "—" : `${Math.round(stats.traps.catch_rate * 100)}%`;

  return (
    <div className="rv-shell">
      <div className="rv-header">
        <Link href="/dashboard" className="rv-back">← Dashboard</Link>
        <span className="rv-title">Bàn duyệt luật sư</span>
        {duty && (
          <div className="rv-duty">
            <span className="rv-w">{duty.lawyer} · dự phòng: {duty.backup}</span>
            <button className={`rv-btn ${duty.on_duty ? "rv-btn-ok" : "rv-btn-bad"}`}
              onClick={() => void toggleDuty()}>
              {duty.on_duty ? "Đang trực" : "Không có luật sư trực"}
            </button>
          </div>
        )}
      </div>

      <div className="rv-strip">
        <div className="rv-stat"><b>{pending}</b><span>Ca chờ duyệt</span></div>
        <div className="rv-stat"><b>{rate}</b><span>Tỷ lệ duyệt thẳng</span></div>
        <div className="rv-stat"><b>{trapRate}</b><span>Tỷ lệ bắt ca bẫy</span></div>
        <div className="rv-stat"><b>{top}</b><span>Nhãn lỗi nhiều nhất</span></div>
      </div>

      <div className="rv-autonomy">
        <span className="rv-h">Mức tự chủ</span>
        {levels.map((a) => (
          <label className="rv-autonomy-row" key={a.case_type}>
            <span>{CASE_TYPE_LABEL[a.case_type] ?? a.case_type}</span>
            <select className="rv-select" value={a.level}
              onChange={(e) => void changeLevel(a.case_type, Number(e.target.value))}>
              {[0, 1, 2, 3].map((n) => <option key={n} value={n}>Mức {n}</option>)}
            </select>
            {a.reason && <span className="rv-w">{a.reason}</span>}
          </label>
        ))}
      </div>

      <div className="rv-body">
        <div className="rv-list">
          <div className="rv-tabs">
            {(["pending", "done", "all"] as Filter[]).map((f) => (
              <button key={f} className={`rv-tab ${filter === f ? "on" : ""}`}
                onClick={() => setFilter(f)}>
                {f === "pending" ? "Chờ duyệt" : f === "done" ? "Đã xử lý" : "Tất cả"}
              </button>
            ))}
          </div>
          {loading ? (
            <div className="rv-empty">Đang tải…</div>
          ) : shown.length === 0 ? (
            <div className="rv-empty">Không có ca nào.</div>
          ) : (
            shown.map((c) => (
              <button key={c.id} className={`rv-case ${openId === c.id ? "on" : ""}`}
                onClick={() => setOpenId(c.id)}>
                <div className="rv-case-head">
                  <span className={`rv-chip ${c.risk_score === "inf" || Number(c.risk_score) >= 3 ? "warn" : ""}`}>
                    {c.risk_score === "inf" ? "∞" : c.risk_score}
                  </span>
                  <span className="rv-src">{SOURCE_LABEL[c.source] ?? c.source}</span>
                  <span className={`rv-due ${c.overdue ? "late" : ""}`}>
                    {c.overdue ? "Quá hạn" : dueLabel(c.due_at)}
                  </span>
                  <span className="rv-time">{timeAgo(c.created_at)}</span>
                </div>
                <div className="rv-q">{c.question.slice(0, 120)}</div>
              </button>
            ))
          )}
        </div>

        <div className="rv-panel">
          {!pkg ? (
            <div className="rv-empty">Chọn một ca bên trái.</div>
          ) : (
            <>
              <div className="rv-question">{pkg.question}</div>
              <div className="rv-meta">
                {STATUS_LABEL[pkg.status] ?? pkg.status} · {SOURCE_LABEL[pkg.source] ?? pkg.source}
                {pkg.model ? ` · ${pkg.model}` : ""}{pkg.prompt_version ? ` · prompt ${pkg.prompt_version}` : ""}
              </div>

              {pkg.reasons.length > 0 && (
                <section className="rv-sec">
                  <h3 className="rv-h">Lý do vào hàng đợi</h3>
                  <ul className="rv-reasons">
                    {pkg.reasons.map((r) => (
                      <li key={r.code}>{r.message} <span className="rv-w">({r.weight})</span></li>
                    ))}
                  </ul>
                </section>
              )}

              <section className="rv-sec">
                <h3 className="rv-h">Phương án trả lời</h3>
                <textarea className="rv-draft" rows={8} value={draft} disabled={busy}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={pkg.draft ? "" : "Ca do người dùng gửi — viết câu trả lời ở đây."} />
              </section>

              {pkg.timeframe && (
                <section className="rv-sec"><TimeFrameBox tf={pkg.timeframe} /></section>
              )}

              {pkg.verifier && (pkg.verifier.problems ?? []).length > 0 && (
                <section className="rv-sec">
                  <h3 className="rv-h">Verifier phát hiện</h3>
                  <ul className="rv-problems">
                    {pkg.verifier.problems.map((p, i) => <li key={i}>{p.message}</li>)}
                  </ul>
                </section>
              )}

              {pkg.provisions.length > 0 && (
                <section className="rv-sec">
                  <h3 className="rv-h">Căn cứ đã trích</h3>
                  {pkg.provisions.map((p) => (
                    <details className="rv-prov" key={p.node_id}>
                      <summary>{p.heading ?? p.node_id} <span className="rv-w">{p.node_id}</span></summary>
                      <div className="rv-prov-text">{p.text || "(không có trong kho)"}</div>
                    </details>
                  ))}
                </section>
              )}

              {pkg.status === "pending" ? (
                <section className="rv-sec">
                  <div className="rv-actions">
                    <button className="rv-btn rv-btn-ok" disabled={busy}
                      onClick={() => void act("approve")}>Duyệt thẳng</button>
                    <button className="rv-btn" disabled={busy}
                      onClick={() => void act("light_edit")}>Sửa nhẹ</button>
                    <button className="rv-btn" disabled={busy}
                      onClick={() => setExtra("heavy_edit")}>Sửa nhiều</button>
                    <button className="rv-btn rv-btn-bad" disabled={busy}
                      onClick={() => setExtra("reject")}>Từ chối</button>
                  </div>
                  {extra && (
                    <div className="rv-extra">
                      <div className="rv-labels">
                        {Object.entries(labelNames).map(([key, name]) => (
                          <label className="rv-label" key={key}>
                            <input type="checkbox" checked={chosen.includes(key)} disabled={busy}
                              onChange={() => setChosen((old) =>
                                old.includes(key) ? old.filter((x) => x !== key) : [...old, key])} />
                            {name}
                          </label>
                        ))}
                      </div>
                      <textarea className="rv-reason" rows={2} value={reason} disabled={busy}
                        placeholder={extra === "reject"
                          ? "Lý do từ chối (bắt buộc)"
                          : "Lý do sửa nhiều (tuỳ chọn)"}
                        onChange={(e) => setReason(e.target.value)} />
                      <div className="rv-actions">
                        <button className="rv-btn rv-btn-ok" disabled={busy}
                          onClick={() => void act(extra)}>Xác nhận</button>
                        <button className="rv-btn" disabled={busy}
                          onClick={() => setExtra(null)}>Huỷ</button>
                      </div>
                    </div>
                  )}
                  {err && <div className="rv-err">{err}</div>}
                </section>
              ) : (
                <section className="rv-sec">
                  <h3 className="rv-h">Đã quyết: {STATUS_LABEL[pkg.status] ?? pkg.status}</h3>
                  {(pkg.error_labels ?? []).length > 0 && (
                    <div className="rv-tags">
                      {pkg.error_labels.map((key) => (
                        <span className="rv-tag" key={key}>{labelNames[key] ?? key}</span>
                      ))}
                    </div>
                  )}
                  {pkg.reply && <div className="rv-reply">{pkg.reply}</div>}
                  {pkg.diff && <Diff text={pkg.diff} />}
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
