"use client";

/* GenAI soạn văn bản: luật sư đề xuất mẫu -> admin chỉnh (mỗi lần lưu là một phiên bản) -> chốt và
   khoá (kiểm bằng code) -> soạn văn bản từ mẫu đã khoá. Giao diện tối thiểu; làm đẹp ở bước sau. */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Field = { name: string; label: string; type: string; required: boolean };
type Version = { version: number; body: string; fields: Field[]; legal_basis: string[]; note?: string; author?: string; locked: boolean; locked_by?: string; locked_at?: string };
type Tpl = { id: string; name: string; kind: string; status: string; proposed_by?: string; locked_version?: number; versions?: Version[] };
type Issue = { level: "error" | "warn"; code: string; message: string };
type Gen = { text: string; errors: string[]; ok: boolean; basis: { node_id: string; display: string; status: string }[]; version: number; as_of: string };

const STATUS: Record<string, string> = { proposed: "Đề xuất", draft: "Đang chỉnh", locked: "Đã khoá", archived: "Lưu trữ" };
const KINDS: Record<string, string> = { hop_dong: "Hợp đồng", quyet_dinh: "Quyết định", don: "Đơn", bien_ban: "Biên bản", thong_bao: "Thông báo", quy_che: "Quy chế", khac: "Khác" };
const json = { "Content-Type": "application/json" };

export default function DocGen() {
  const { can } = useAuth();
  const [list, setList] = useState<Tpl[]>([]);
  const [cur, setCur] = useState<Tpl | null>(null);
  const [mode, setMode] = useState<"edit" | "use" | "new">("use");
  const [name, setName] = useState("");
  const [kind, setKind] = useState("hop_dong");
  const [body, setBody] = useState("");
  const [basis, setBasis] = useState("");
  const [note, setNote] = useState("");
  const [issues, setIssues] = useState<Issue[]>([]);
  const [fields, setFields] = useState<Field[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [gen, setGen] = useState<Gen | null>(null);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    const r = await apiFetch("/api/docgen/templates");
    if (r.ok) setList((await r.json()).templates);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const open = async (id: string, m: "edit" | "use") => {
    const r = await apiFetch(`/api/docgen/templates/${id}`);
    if (!r.ok) return;
    const t: Tpl = await r.json();
    const v = t.versions![t.versions!.length - 1];
    setCur(t); setMode(m); setName(t.name); setKind(t.kind); setBody(v.body); setBasis(v.legal_basis.join(", "));
    setNote(v.note || ""); setFields(v.fields); setGen(null); setValues({}); setMsg("");
  };

  // kiểm bằng code khi gõ (không gọi AI)
  useEffect(() => {
    if (mode === "use" || !body) return;
    const t = setTimeout(async () => {
      const r = await apiFetch("/api/docgen/lint", { method: "POST", headers: json, body: JSON.stringify({ body, legal_basis: basisList(basis), fields }) });
      if (r.ok) { const b = await r.json(); setIssues(b.issues); setFields(b.fields); }
    }, 400);
    return () => clearTimeout(t);
  }, [body, basis, mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const lockedV = useMemo(() => cur?.versions?.find((v) => v.version === cur.locked_version), [cur]);

  const propose = async () => {
    const r = await apiFetch("/api/docgen/templates", { method: "POST", headers: json, body: JSON.stringify({ name, kind, body, legal_basis: basisList(basis), note }) });
    const b = await r.json();
    if (!r.ok) { setMsg(b.detail || "Lỗi"); return; }
    setMsg("Đã gửi đề xuất, chờ admin chỉnh và chốt"); await load(); await open(b.id, "edit");
  };
  const save = async () => {
    const r = await apiFetch(`/api/docgen/templates/${cur!.id}`, { method: "PUT", headers: json, body: JSON.stringify({ body, fields, legal_basis: basisList(basis), note }) });
    setMsg(r.ok ? "Đã lưu phiên bản" : "Không lưu được"); if (r.ok) { await load(); await open(cur!.id, "edit"); }
  };
  const lock = async () => {
    const r = await apiFetch(`/api/docgen/templates/${cur!.id}/lock`, { method: "POST" });
    const b = await r.json();
    if (!r.ok) { setIssues(b.detail?.issues || []); setMsg("Chưa khoá được: còn lỗi bên dưới"); return; }
    setMsg("Đã chốt và khoá. Mẫu dùng được để soạn."); await load(); await open(cur!.id, "use");
  };
  const generate = async () => {
    const r = await apiFetch(`/api/docgen/templates/${cur!.id}/generate`, { method: "POST", headers: json, body: JSON.stringify({ values }) });
    const b = await r.json();
    if (!r.ok) { setMsg(b.detail || "Lỗi"); return; }
    setGen(b);
  };
  const suggest = async (f: Field) => {
    setMsg("Đang gợi ý câu chữ…");
    const ctx = Object.entries(values).map(([k, v]) => `${k}: ${v}`).join("\n");
    const r = await apiFetch("/api/docgen/suggest", { method: "POST", headers: json, body: JSON.stringify({ label: f.label, context: `${name}\n${ctx}` }) });
    const b = await r.json();
    if (r.ok) { setValues((v) => ({ ...v, [f.name]: b.text })); setMsg(b.note); } else setMsg(b.detail || "Chưa gợi ý được");
  };

  const useFields = lockedV?.fields || [];
  return (
    <main className="collect-page">
      <header className="collect-head">
        <Link href="/" className="auth-link">← Trợ lý</Link>
        <h1>Soạn văn bản từ mẫu</h1>
        <p className="vi-note">Luật sư đề xuất mẫu → admin chỉnh → chốt và khoá (kiểm bằng code) → soạn. Mẫu đã khoá không sửa; sửa tiếp là phiên bản mới.</p>
      </header>
      <div className="dg-layout">
        <aside className="dg-list">
          {can("escalate") && <button className="vi-btn primary" onClick={() => { setCur(null); setMode("new"); setName(""); setBody(""); setBasis(""); setNote(""); setGen(null); }}>+ Đề xuất mẫu mới</button>}
          {list.map((t) => (
            <div key={t.id} className={`dg-item ${cur?.id === t.id ? "active" : ""}`}>
              <strong>{t.name}</strong>
              <small>{KINDS[t.kind] || t.kind} · <span className={`collect-use ${t.status === "locked" ? "ok" : "wip"}`}>{STATUS[t.status]}</span>{t.locked_version ? ` v${t.locked_version}` : ""}</small>
              <div className="dg-actions">
                {t.locked_version && <button className="vi-btn" onClick={() => open(t.id, "use")}>Soạn</button>}
                {can("upload") && <button className="vi-btn" onClick={() => open(t.id, "edit")}>Chỉnh</button>}
              </div>
            </div>
          ))}
          {!list.length && <p className="vi-note">Chưa có mẫu nào.</p>}
        </aside>

        <section className="dg-main">
          {(mode === "new" || mode === "edit") && (
            <>
              <div className="dg-row">
                <input className="vi-repl" placeholder="Tên mẫu" value={name} onChange={(e) => setName(e.target.value)} disabled={mode === "edit"} />
                <select className="vi-repl" value={kind} onChange={(e) => setKind(e.target.value)} disabled={mode === "edit"}>
                  {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              <label className="vi-label">Nội dung (biến viết dạng {"{{ho_ten}}"}, {"{{ngay_bat_dau}}"}, {"{{muc_luong}}"})</label>
              <textarea className="vi-text dg-body" rows={14} value={body} onChange={(e) => setBody(e.target.value)} />
              <label className="vi-label">Căn cứ pháp lý (mã điều, cách nhau dấu phẩy, ví dụ blld2019-d21)</label>
              <input className="vi-repl" value={basis} onChange={(e) => setBasis(e.target.value)} />
              <label className="vi-label">Ghi chú</label>
              <input className="vi-repl" value={note} onChange={(e) => setNote(e.target.value)} />
              {fields.length > 0 && (
                <div className="dg-fields">
                  <strong>Trường ({fields.length})</strong>
                  {fields.map((f, i) => (
                    <div key={f.name} className="dg-row">
                      <code>{f.name}</code>
                      <input className="vi-repl" value={f.label} onChange={(e) => setFields((fs) => fs.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
                      <select className="vi-repl" value={f.type} onChange={(e) => setFields((fs) => fs.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}>
                        {["text", "date", "money", "number", "long_text"].map((t) => <option key={t}>{t}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
              )}
              <ul className="dg-issues">
                {issues.map((i, k) => <li key={k} className={i.level}>{i.level === "error" ? "✖" : "⚠"} {i.message}</li>)}
                {!issues.length && body && <li className="ok">✔ Không có lỗi</li>}
              </ul>
              <div className="vi-actions">
                {mode === "new" && <button className="vi-btn primary" onClick={propose}>Gửi đề xuất</button>}
                {mode === "edit" && can("upload") && <>
                  <button className="vi-btn" onClick={save}>Lưu phiên bản</button>
                  <button className="vi-btn primary" disabled={issues.some((i) => i.level === "error")} onClick={lock}>Chốt và khoá</button>
                </>}
              </div>
              {cur?.versions && (
                <details className="help-entry"><summary>Lịch sử phiên bản ({cur.versions.length})</summary>
                  {cur.versions.map((v) => <p key={v.version}>v{v.version} · {v.locked ? `🔒 khoá bởi ${v.locked_by}` : "đang chỉnh"} · {v.author} · {v.note}</p>)}
                </details>
              )}
            </>
          )}

          {mode === "use" && cur && lockedV && (
            <>
              <h2>{cur.name} <small className="vi-note">🔒 v{lockedV.version}</small></h2>
              {useFields.map((f) => (
                <div key={f.name} className="dg-field">
                  <label className="vi-label">{f.label}{f.required ? " *" : ""} <small>({f.type})</small></label>
                  {f.type === "long_text" ? (
                    <>
                      <textarea className="vi-text" rows={3} value={values[f.name] || ""} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
                      {can("escalate") && <button className="vi-btn" onClick={() => suggest(f)}>✨ Gợi ý câu chữ</button>}
                    </>
                  ) : (
                    <input className="vi-repl" placeholder={f.type === "date" ? "dd/mm/yyyy" : f.type === "money" ? "12500000" : ""}
                      value={values[f.name] || ""} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
                  )}
                </div>
              ))}
              <div className="vi-actions"><button className="vi-btn primary" onClick={generate}>Soạn văn bản</button></div>
              {gen && (
                <div className="dg-out">
                  {gen.errors.length > 0 && <ul className="dg-issues">{gen.errors.map((e) => <li key={e} className="error">✖ {e}</li>)}</ul>}
                  <pre className="vi-preview">{gen.text}</pre>
                  <strong>Căn cứ (áp dụng tại {gen.as_of.split("-").reverse().join("/")})</strong>
                  <ul>{gen.basis.map((b) => <li key={b.node_id}>{b.status === "active" ? "✔" : "⏳"} {b.display}</li>)}</ul>
                  <button className="vi-btn" onClick={() => navigator.clipboard?.writeText(gen.text)}>Sao chép</button>
                </div>
              )}
            </>
          )}
          {!cur && mode !== "new" && <p className="vi-note">Chọn một mẫu ở bên trái để soạn văn bản.</p>}
          {msg && <p className="vi-note">{msg}</p>}
        </section>
      </div>
    </main>
  );
}

function basisList(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}
