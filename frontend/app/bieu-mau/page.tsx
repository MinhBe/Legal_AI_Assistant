"use client";

/* Thư viện biểu mẫu (TPL1): tải lên, tìm, tải về, lưu trữ.
   Biểu mẫu KHÔNG dùng làm căn cứ trả lời; backend: /api/templates (app/templates_lib). */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { apiFetch } from "@/lib/api";
import { RequirePerm, useAuth } from "@/lib/auth";

const KINDS: Record<string, string> = {
  hop_dong: "Hợp đồng",
  quyet_dinh: "Quyết định",
  don: "Đơn",
  bien_ban: "Biên bản",
  thong_bao: "Thông báo",
  quy_che: "Quy chế",
  khac: "Khác",
};

type TemplateRow = {
  id: string; name: string; kind: string; description: string | null;
  legal_basis: string[]; filename: string; mime: string | null; size_bytes: number;
  text_preview: string | null; placeholders: string[]; version: number;
  status: string; created_by: string; created_at: string | null;
};

const kindLabel = (k: string) => KINDS[k] ?? k;

function TestLegalBasis({ ids }: { ids: string[] }) {
  const [state, setState] = useState<Record<string, boolean | null>>({});
  async function check() {
    const next: Record<string, boolean | null> = {};
    for (const id of ids) {
      try {
        const r = await apiFetch(`/api/law/${encodeURIComponent(id)}`);
        next[id] = r.ok;
      } catch {
        next[id] = null;
      }
    }
    setState(next);
  }
  const text = ids.length === 0 ? "chưa nhập" : ids
    .map((id) => {
      const ok = state[id];
      return `${id} ${ok === true ? "✓" : ok === false ? "✗" : "?"}`;
    })
    .join(" · ");
  return (
    <div className="tpl-check">
      <button type="button" className="tpl-btn" onClick={check}>kiểm tra</button>
      <span className="tpl-check-text">{text}</span>
    </div>
  );
}

export default function TemplatesPage() {
  return (
    <RequirePerm perm="review">
      <TemplatesPageInner />
    </RequirePerm>
  );
}

function TemplatesPageInner() {
  const { can } = useAuth();
  const mayUpload = can("upload");
  const [rows, setRows] = useState<TemplateRow[]>([]);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [formKind, setFormKind] = useState("hop_dong");
  const [description, setDescription] = useState("");
  const [basis, setBasis] = useState("");

  const refresh = useCallback(async () => {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (kind) params.set("kind", kind);
    try {
      const r = await apiFetch(`/api/templates?${params.toString()}`);
      setRows(r.ok ? await r.json() : []);
    } catch {
      setRows([]);
    }
  }, [q, kind]);

  useEffect(() => { refresh(); }, [refresh]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) { setErr("Chọn tệp biểu mẫu trước"); return; }
    setBusy(true);
    setErr("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("name", name.trim() || file.name);
      fd.append("kind", formKind);
      if (description.trim()) fd.append("description", description.trim());
      fd.append("legal_basis", basis);
      const r = await apiFetch("/api/templates", { method: "POST", body: fd });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        setErr(r.status === 409 ? `Tệp này đã có (${body.id ?? "?"})` : body.detail || `Lỗi ${r.status}`);
        return;
      }
      setFile(null);
      setName("");
      setDescription("");
      setBasis("");
      await refresh();
    } catch {
      setErr("Không kết nối được API");
    } finally {
      setBusy(false);
    }
  }

  async function download(row: TemplateRow) {
    try {
      const r = await apiFetch(`/api/templates/${row.id}/file`);
      if (!r.ok) return;
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = row.filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* bỏ qua */ }
  }

  async function archive(row: TemplateRow) {
    if (!confirm(`Lưu trữ biểu mẫu "${row.name}"?`)) return;
    try { await apiFetch(`/api/templates/${row.id}`, { method: "DELETE" }); }
    finally { await refresh(); }
  }

  const basisIds = basis.split(",").map((s) => s.trim()).filter(Boolean);

  return (
    <div className="dash-shell">
      <div className="dash-header">
        <Link href="/" className="dash-back">← Chat</Link>
        <span className="dash-title">Biểu mẫu</span>
      </div>

      <div className="dash-body">
        <p className="up-note">
          Biểu mẫu không dùng làm căn cứ trả lời; tự điền mẫu sẽ có ở bản sau.
        </p>

        {mayUpload && (
          <form className="tpl-form" onSubmit={submit}>
            <div className="tpl-form-row">
              <label className="tpl-field">
                Tệp (.docx, .pdf, .xlsx, .doc · tối đa 20 MB)
                <input type="file" accept=".docx,.pdf,.xlsx,.doc"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
              <label className="tpl-field">
                Tên biểu mẫu
                <input value={name} onChange={(e) => setName(e.target.value)}
                  placeholder="Mẫu hợp đồng lao động" />
              </label>
              <label className="tpl-field">
                Loại
                <select value={formKind} onChange={(e) => setFormKind(e.target.value)}>
                  {Object.entries(KINDS).map(([k, label]) => (
                    <option key={k} value={k}>{label}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="tpl-form-row">
              <label className="tpl-field">
                Mô tả
                <input value={description} onChange={(e) => setDescription(e.target.value)}
                  placeholder="Dùng cho nhân viên thử việc" />
              </label>
              <label className="tpl-field">
                Căn cứ (các node_id, cách nhau bằng dấu phẩy)
                <input value={basis} onChange={(e) => setBasis(e.target.value)}
                  placeholder="blld2019-d20, blld2019-d21" />
              </label>
            </div>
            <TestLegalBasis ids={basisIds} />
            {err && <div className="up-line up-err">{err}</div>}
            <button className="tpl-btn tpl-btn-main" type="submit" disabled={busy}>
              {busy ? "Đang tải…" : "Tải biểu mẫu lên"}
            </button>
          </form>
        )}

        <div className="tpl-filter">
          <input value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Tìm theo tên, mô tả, nội dung…" />
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Mọi loại</option>
            {Object.entries(KINDS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </div>

        <div className="dash-card">
          <div className="dash-card-title">Biểu mẫu ({rows.length})</div>
          {rows.length === 0 ? (
            <div className="dash-empty">Chưa có biểu mẫu nào.</div>
          ) : (
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Tên</th><th>Loại</th><th>Phiên bản</th><th>Căn cứ</th>
                  <th>Chỗ trống</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td title={row.description || undefined}>
                      {row.name}
                      <div className="tpl-file">{row.filename}</div>
                    </td>
                    <td>{kindLabel(row.kind)}</td>
                    <td>{row.version}</td>
                    <td className="tpl-chips">
                      {row.legal_basis.map((id) => (
                        <a key={id} className="tpl-chip" href={`/api/law/${id}`} target="_blank"
                          rel="noreferrer">{id}</a>
                      ))}
                    </td>
                    <td>{row.placeholders.length}</td>
                    <td className="tpl-actions">
                      <button className="tpl-btn" onClick={() => download(row)}>Tải về</button>
                      {mayUpload && (
                        <button className="tpl-btn tpl-btn-del" onClick={() => archive(row)}>
                          Lưu trữ
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
