"use client";

/* Trang tải tài liệu lên: OCR + nạp vào knowledge graph, rồi duyệt/loại/xoá.
   Backend: POST/GET/PATCH/DELETE /api/uploads (app/upload). Mặc định mức A, chờ duyệt. */
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { apiFetch } from "@/lib/api";
import { RequirePerm } from "@/lib/auth";

const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.docx,.txt,.md,.mp3,.m4a,.wav,.ogg,.webm,.mp4,.mov,.mkv";
//: tệp ghi âm/ghi hình: đi đường chép lời (AU1), cần xác nhận đồng ý trước khi gửi
const AUDIO_RE = /\.(mp3|m4a|wav|ogg|webm|mp4|mov|mkv)$/i;
const isAudio = (name: string) => AUDIO_RE.test(name);
const CONSENT = "Người được ghi âm đã đồng ý cho dùng bản ghi này";

type UploadRow = {
  upload_id: string; doc_id: string | null; filename: string; mime: string;
  size_bytes: number; pages: number | null; ocr_pages: number | null;
  chars: number | null; mean_ocr_conf: number | null; parse_mode: string | null;
  n_nodes: number | null; n_refs: number | null; data_class: string | null;
  status: string; error: string | null; preview: string | null;
  created_at: string | null; duplicate?: boolean;
};

const STATUS: Record<string, { label: string; cls: string }> = {
  processing: { label: "Đang xử lý…", cls: "warn" },
  pending_review: { label: "chờ duyệt", cls: "warn" },
  approved: { label: "đã duyệt", cls: "ok" },
  rejected: { label: "đã loại", cls: "err" },
  failed: { label: "lỗi", cls: "err" },
};
const statusOf = (s: string) => STATUS[s] ?? { label: s, cls: "" };

const parseMode = (m: string | null) =>
  m === "articles" ? "Điều/Khoản" : m === "sections" ? "Đoạn" : "—";

type UploadJob = {
  upload_id: string; kind: string; stage: string; progress: number;
  message: string | null; duration_s: number | null; consent: boolean;
};

const STAGE: Record<string, string> = {
  converting: "Đang chuyển định dạng",
  transcribing: "Đang chép lời",
  masking: "Đang che dữ liệu cá nhân",
  extracting: "Đang rút ca tư vấn",
  done: "Xong",
  failed: "Lỗi",
};

type DocNode = {
  node_id: string; level: string; heading: string; preview: string; refs: string[];
};

// mean_ocr_conf là 0..1; lưu cũ có thể là phần trăm
const confPct = (c: number | null) =>
  c == null ? "—" : `${Math.round((c <= 1 ? c : c / 100) * 100)}%`;

export default function UploadPage() {
  return (
    <RequirePerm perm="upload">
      <UploadPageInner />
    </RequirePerm>
  );
}

function UploadPageInner() {
  const [rows, setRows] = useState<UploadRow[]>([]);
  const [busy, setBusy] = useState<string[]>([]);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  // toàn văn theo upload_id; danh sách chỉ có preview 2000 ký tự đầu
  const [fullText, setFullText] = useState<Record<string, string>>({});
  // node theo upload_id, tải khi bấm "Xem node"
  const [nodes, setNodes] = useState<Record<string, DocNode[]>>({});
  const [openNodes, setOpenNodes] = useState<string | null>(null);
  // tiến trình chép lời theo upload_id (chỉ tệp ghi âm/ghi hình mới có)
  const [jobs, setJobs] = useState<Record<string, UploadJob>>({});
  const [consent, setConsent] = useState(false);

  async function toggleNodes(id: string) {
    setOpenNodes((o) => (o === id ? null : id));
    if (nodes[id] !== undefined) return;
    try {
      const r = await apiFetch(`/api/uploads/${id}/nodes`);
      if (r.ok) {
        const d = await r.json();
        setNodes((m) => ({ ...m, [id]: d.nodes || [] }));
      }
    } catch { /* bỏ trống */ }
  }

  async function toggleText(id: string) {
    setOpen((o) => (o === id ? null : id));
    if (fullText[id] !== undefined) return;
    try {
      const r = await apiFetch(`/api/uploads/${id}/text`);
      if (r.ok) {
        const d = await r.json();
        setFullText((m) => ({ ...m, [id]: d.text || "" }));
      }
    } catch { /* giữ preview */ }
  }
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch(`/api/uploads`);
      setRows(r.ok ? await r.json() : []);
    } catch { setRows([]); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // còn tệp đang xử lý ở nền -> hỏi lại mỗi 2 giây, xong hết thì dừng
  useEffect(() => {
    if (!rows.some((r) => r.status === "processing")) return;
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, [rows, refresh]);

  // tệp đang chép lời -> hỏi tiến trình mỗi 3 giây (giai đoạn + thanh tiến trình)
  useEffect(() => {
    const ids = rows
      .filter((r) => isAudio(r.filename) && r.status === "processing")
      .map((r) => r.upload_id);
    if (ids.length === 0) return;
    let alive = true;
    const tick = async () => {
      for (const id of ids) {
        try {
          const r = await apiFetch(`/api/uploads/${id}/job`);
          if (!r.ok) continue;
          const job: UploadJob = await r.json();
          if (alive) setJobs((m) => ({ ...m, [id]: job }));
        } catch { /* lần sau hỏi lại */ }
      }
    };
    tick();
    const h = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(h); };
  }, [rows]);

  /* tải lần lượt từng tệp: "Đang xử lý…" rồi kết quả hoặc lỗi detail */
  async function send(files: File[]) {
    for (const f of files) {
      if (isAudio(f.name) && !consent) {
        // chưa xác nhận đồng ý thì không gửi: bản ghi có tiếng người khác
        setErrs((e) => ({ ...e, [f.name]: CONSENT }));
        continue;
      }
      setBusy((b) => [...b, f.name]);
      setErrs((e) => { const n = { ...e }; delete n[f.name]; return n; });
      const fd = new FormData();
      fd.append("file", f);
      if (isAudio(f.name)) fd.append("consent", "true");
      let detail = "";
      try {
        const r = await apiFetch(`/api/uploads`, { method: "POST", body: fd });
        if (!r.ok) {
          detail = `Lỗi ${r.status}`;
          try { detail = (await r.json()).detail || detail; } catch { /* không phải JSON */ }
        }
      } catch { detail = "Không kết nối được API"; }
      finally {
        setBusy((b) => b.filter((x) => x !== f.name));
        if (detail) setErrs((e) => ({ ...e, [f.name]: detail }));
        await refresh();
      }
    }
  }

  async function review(id: string, status: "approved" | "rejected") {
    try {
      await apiFetch(`/api/uploads/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
    } finally { await refresh(); }
  }

  async function remove(id: string) {
    if (!confirm("Xoá tài liệu này? Node và dẫn chiếu của nó cũng bị xoá khỏi đồ thị.")) return;
    try { await apiFetch(`/api/uploads/${id}`, { method: "DELETE" }); }
    finally { await refresh(); }
  }

  const pending = busy.length + Object.keys(errs).length;

  return (
    <div className="dash-shell">
      <div className="dash-header">
        <Link href="/" className="dash-back">← Chat</Link>
        <span className="dash-title">Tải tài liệu lên</span>
        <Link href="/graph" className="dash-graph-btn">Knowledge Graph</Link>
      </div>

      <div className="dash-body">
        <p className="up-note">
          Tài liệu được OCR và đưa vào knowledge graph ngay trong máy. Mặc định là dữ liệu mức A,
          chờ duyệt, không được dùng làm căn cứ khi trả lời chat.
        </p>

        <div
          className={`up-drop${over ? " over" : ""}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault(); setOver(false);
            const files = Array.from(e.dataTransfer.files || []);
            if (files.length) send(files);
          }}>
          <b>Kéo tệp vào đây hoặc bấm để chọn</b>
          <span>PDF, ảnh scan (PNG/JPG/TIFF/BMP/WebP), DOCX, TXT, MD · tối đa 20 MB · 50 trang</span>
          <span>Ghi âm/ghi hình buổi tư vấn: MP3, M4A, WAV, OGG, WEBM, MP4, MOV, MKV · tối đa 600 MB</span>
          <input ref={inputRef} type="file" multiple accept={ACCEPT} hidden
            onChange={(e) => {
              const files = Array.from(e.target.files || []);
              e.target.value = "";
              if (files.length) send(files);
            }} />
        </div>

        {pending > 0 && (
          <div className="up-list">
            {busy.map((name) => (
              <div key={`b-${name}`} className="up-line">Đang xử lý… {name}</div>
            ))}
            {Object.entries(errs).map(([name, detail]) => (
              <div key={`e-${name}`} className="up-line up-err">{name}: {detail}</div>
            ))}
          </div>
        )}

        <label className="au-consent">
          <input type="checkbox" checked={consent}
            onChange={(e) => setConsent(e.target.checked)} />
          {CONSENT} (bắt buộc với tệp ghi âm/ghi hình)
        </label>

        <div className="dash-card">
          <div className="dash-card-title">Tài liệu đã tải lên ({rows.length})</div>
          {rows.length === 0 ? (
            <div className="dash-empty">Chưa có tài liệu nào.</div>
          ) : (
            <table className="dash-table up-table">
              <thead>
                <tr>
                  <th>Tệp</th><th>Trạng thái</th><th>Trang</th><th>Trang OCR</th>
                  <th>Độ tin cậy OCR</th><th>Cách tách</th><th>Nodes</th><th>Dẫn chiếu</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const st = statusOf(r.status);
                  const isOpen = open === r.upload_id;
                  const job = jobs[r.upload_id];
                  return [
                    <tr key={r.upload_id} className={`up-row${isOpen ? " open" : ""}`}
                      title={r.error || undefined}
                      onClick={() => toggleText(r.upload_id)}>
                      <td className="up-name">
                        {r.filename}
                        {r.duplicate && <span className="up-dup"> · đã có</span>}
                      </td>
                      <td><span className={`badge ${st.cls}`}>{st.label}</span>
                        {job && (
                          <div className="au-stage" title={job.message || undefined}>
                            <span>{STAGE[job.stage] ?? job.stage}</span>
                            <div className="au-bar">
                              <div className="au-fill"
                                style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
                            </div>
                          </div>
                        )}
                      </td>
                      <td>{r.pages ?? "—"}</td>
                      <td>{r.ocr_pages ?? "—"}</td>
                      <td>{confPct(r.mean_ocr_conf)}</td>
                      <td>{parseMode(r.parse_mode)}</td>
                      <td>{r.n_nodes ?? "—"}</td>
                      <td>{r.n_refs ?? "—"}</td>
                      <td className="up-actions" onClick={(e) => e.stopPropagation()}>
                        {r.doc_id && <Link href={`/graph?doc_id=${encodeURIComponent(r.doc_id)}`} className="up-btn">Xem trên graph</Link>}
                        <button className="up-btn" onClick={() => toggleNodes(r.upload_id)}>Xem node</button>
                        <button className="up-btn" disabled={r.status !== "pending_review"}
                          onClick={() => review(r.upload_id, "approved")}>Duyệt</button>
                        <button className="up-btn" disabled={r.status === "rejected"}
                          onClick={() => review(r.upload_id, "rejected")}>Loại</button>
                        <button className="up-btn up-btn-del" onClick={() => remove(r.upload_id)}>Xoá</button>
                      </td>
                    </tr>,
                    isOpen && (
                      <tr key={`${r.upload_id}-preview`} className="up-preview-row">
                        <td colSpan={9}>
                          {fullText[r.upload_id] !== undefined && (
                            <div className="up-note">Toàn văn: {fullText[r.upload_id].length.toLocaleString("vi-VN")} ký tự</div>
                          )}
                          <div className="up-preview">
                            {fullText[r.upload_id] ?? (r.preview || r.error || "Không có nội dung xem trước.")}
                          </div>
                        </td>
                      </tr>
                    ),
                    openNodes === r.upload_id && (
                      <tr key={`${r.upload_id}-nodes`} className="up-preview-row">
                        <td colSpan={9}>
                          {nodes[r.upload_id] === undefined ? (
                            <div className="up-note">Đang tải node…</div>
                          ) : nodes[r.upload_id].length === 0 ? (
                            <div className="up-note">Tệp chưa có node nào.</div>
                          ) : (
                            <div className="up-nodes">
                              {nodes[r.upload_id].map((n) => (
                                <div className="up-nodes-item" key={n.node_id}>
                                  <div className="up-nodes-head">
                                    <span className="up-nodes-level">{n.level}</span>
                                    {n.heading || n.node_id}
                                  </div>
                                  <div className="up-nodes-preview">{n.preview}</div>
                                  {n.refs.length > 0 && (
                                    <div className="up-nodes-refs">
                                      {n.refs.map((t) => <span className="up-nodes-ref" key={t}>{t}</span>)}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
