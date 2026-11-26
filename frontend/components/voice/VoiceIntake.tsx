"use client";

/* Voice intake (docs/design/voice-intake.md): ghi âm có chữ hiện ngay, kéo thả tệp,
   duyệt làm mờ từng đoạn nhạy cảm, đồng ý rồi mới lưu. */
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_BASE, apiFetch, authHeaders } from "@/lib/api";
import { emit } from "@/components/help/Coach";
import { LiveMic, type SttEvent } from "@/lib/voice/mic";

type Span = {
  id: string; type: string; group: string; entity: string; text: string;
  start: number; end: number; suggestion: string; default: string;
};
type Decision = { action: string; replacement?: string };
type FileJob = { name: string; size: number; progress: number; status: "uploading" | "transcribing" | "done" | "error"; error?: string };

const GROUPS: Record<string, string> = {
  person: "Tên người", organization: "Công ty, tổ chức", contact: "Địa chỉ, số giấy tờ, điện thoại",
  sensitive_fact: "Tình tiết nhạy cảm",
};
const ACTION_LABEL: Record<string, string> = { pseudonym: "Thay tên giả", generalize: "Làm chung chung", keep: "Giữ nguyên" };
const MEDIA = /\.(mp3|m4a|wav|aac|ogg|webm|mp4|mov|mkv|m4v)$/i;

function uploadFile(file: File, onProgress: (p: number) => void): Promise<{ text: string }> {
  return new Promise((ok, fail) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/stt/file`);
    for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) ok(body); else fail(new Error(body.detail || `Lỗi ${xhr.status}`));
      } catch { fail(new Error(`Lỗi ${xhr.status}`)); }
    };
    xhr.onerror = () => fail(new Error("Mất kết nối"));
    const fd = new FormData();
    fd.append("file", file);
    xhr.send(fd);
  });
}

export default function VoiceIntake({ open, initialFiles, onClose, onUseText }: {
  open: boolean;
  initialFiles?: File[];
  onClose: () => void;
  onUseText: (text: string) => void;
}) {
  const [step, setStep] = useState<"capture" | "review" | "consent" | "saved">("capture");
  const [transcript, setTranscript] = useState("");
  const [partial, setPartial] = useState("");
  const [recording, setRecording] = useState(false);
  const [jobs, setJobs] = useState<FileJob[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [spans, setSpans] = useState<Span[]>([]);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [preview, setPreview] = useState("");
  const [kept, setKept] = useState(0);
  const [consentCase, setConsentCase] = useState(false);
  const [consentTrain, setConsentTrain] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<{ intake_id: string; text: string; data_class: string; consent_training: boolean } | null>(null);
  const [source, setSource] = useState<"live" | "file" | "text">("text");
  const mic = useRef<LiveMic | null>(null);

  const reset = () => {
    setStep("capture"); setTranscript(""); setPartial(""); setJobs([]); setSpans([]); setDecisions({});
    setPreview(""); setKept(0); setConsentCase(false); setConsentTrain(false); setError(""); setSaved(null);
  };

  const addFiles = useCallback((files: File[]) => {
    const media = files.filter((f) => MEDIA.test(f.name) || f.type.startsWith("audio/") || f.type.startsWith("video/"));
    if (!media.length) { setError("Chỉ nhận tệp ghi âm hoặc ghi hình"); return; }
    setSource("file");
    media.forEach((f) => {
      setJobs((js) => [...js, { name: f.name, size: f.size, progress: 0, status: "uploading" }]);
      const upd = (patch: Partial<FileJob>) => setJobs((js) => js.map((j) => (j.name === f.name ? { ...j, ...patch } : j)));
      uploadFile(f, (p) => upd({ progress: p, status: p >= 1 ? "transcribing" : "uploading" }))
        .then((r) => { upd({ status: "done", progress: 1 }); setTranscript((t) => (t ? `${t}\n\n` : "") + `[${f.name}]\n${r.text}`); })
        .catch((e: Error) => upd({ status: "error", error: e.message }));
    });
  }, []);

  useEffect(() => { if (open && initialFiles?.length) addFiles(initialFiles); }, [open, initialFiles, addFiles]);
  useEffect(() => { if (open) emit("voice-opened"); }, [open]);
  const hasText = transcript.trim().length > 0;
  useEffect(() => { if (hasText) emit("transcript-ready"); }, [hasText]);

  const onEvent = useCallback((e: SttEvent) => {
    if (e.type === "partial") setPartial(e.text || "");
    if (e.type === "final") { setPartial(""); setTranscript((t) => (t ? `${t} ` : "") + (e.text || "")); }
    if (e.type === "error") { setError(e.text || "Lỗi chép lời"); setRecording(false); }
  }, []);

  const toggleMic = async () => {
    setError("");
    if (recording) {
      setRecording(false);
      await mic.current?.stop();
      setTimeout(() => mic.current?.close(), 4000);
      return;
    }
    try {
      mic.current = new LiveMic(onEvent);
      await mic.current.start();
      setSource("live");
      setRecording(true);
    } catch {
      setError("Không mở được micro hoặc máy chủ chép lời");
    }
  };

  const goReview = async () => {
    setError("");
    const r = await apiFetch("/api/intake/detect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: transcript }) });
    if (!r.ok) { setError("Không phân tích được nội dung"); return; }
    const body = await r.json();
    setSpans(body.spans);
    setDecisions({});
    setStep("review");
    emit("review-shown");
  };

  // xem trước bản đã làm mờ mỗi khi đổi lựa chọn
  useEffect(() => {
    if (step !== "review" && step !== "consent") return;
    const t = setTimeout(async () => {
      const r = await apiFetch("/api/intake/apply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: transcript, decisions }) });
      if (r.ok) { const b = await r.json(); setPreview(b.text); setKept(b.kept); }
    }, 250);
    return () => clearTimeout(t);
  }, [decisions, transcript, step]);

  const setAction = (s: Span, action: string) => {
    setDecisions((d) => ({ ...d, [s.id]: { ...d[s.id], action } }));
    emit("mask-chosen");
  };
  const setRepl = (s: Span, replacement: string) => {
    // tên giả nhất quán: đổi một đoạn là đổi mọi đoạn cùng người
    setDecisions((d) => {
      const next = { ...d };
      spans.filter((x) => x.entity === s.entity).forEach((x) => { next[x.id] = { action: next[x.id]?.action || x.default, replacement }; });
      return next;
    });
  };

  const grouped = useMemo(() => {
    const g: Record<string, Span[]> = {};
    spans.forEach((s) => { (g[s.group] ||= []).push(s); });
    return g;
  }, [spans]);

  const highlighted = useMemo(() => {
    const out: ReactNode[] = [];
    let i = 0;
    [...spans].sort((a, b) => a.start - b.start).forEach((s) => {
      if (s.start < i) return;
      out.push(transcript.slice(i, s.start));
      const act = decisions[s.id]?.action || s.default;
      out.push(<mark key={s.id} className={`vi-mark vi-${s.group} ${act === "keep" ? "vi-keep" : ""}`} title={`${s.type}: ${ACTION_LABEL[act]}`}>{transcript.slice(s.start, s.end)}</mark>);
      i = s.end;
    });
    out.push(transcript.slice(i));
    return out;
  }, [spans, decisions, transcript]);

  const submit = async () => {
    setError("");
    const r = await apiFetch("/api/intake/submit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: transcript, decisions, consent_case: consentCase, consent_training: consentTrain, source }),
    });
    const b = await r.json().catch(() => ({}));
    if (!r.ok) { setError(b.detail || "Không lưu được"); return; }
    setSaved(b);
    setStep("saved");
  };

  if (!open) return null;
  return (
    <div className="vi-backdrop" role="dialog" aria-modal="true" aria-label="Ghi âm và làm mờ">
      <div className="vi-panel">
        <header className="vi-head">
          <strong>{{ capture: "Ghi âm hoặc đính kèm", review: "Chọn phần cần làm mờ", consent: "Đồng ý", saved: "Đã lưu" }[step]}</strong>
          <button className="icon-btn" onClick={() => { mic.current?.close(); reset(); onClose(); }} aria-label="Đóng">✕</button>
        </header>

        {step === "capture" && (
          <div className="vi-body">
            <div data-tour="voice-drop" className={`vi-drop ${dragOver ? "over" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); addFiles(Array.from(e.dataTransfer.files)); }}>
              <p>Kéo thả tệp ghi âm hoặc video vào đây</p>
              <label className="vi-btn">
                Chọn tệp
                <input type="file" multiple accept="audio/*,video/*" hidden onChange={(e) => addFiles(Array.from(e.target.files || []))} />
              </label>
              <button className={`vi-btn ${recording ? "vi-rec" : ""}`} onClick={toggleMic}>
                {recording ? "■ Dừng ghi âm" : "● Ghi âm"}
              </button>
            </div>
            {jobs.length > 0 && (
              <ul className="vi-jobs">
                {jobs.map((j) => (
                  <li key={j.name}>
                    <span>{j.name}</span>
                    <progress value={j.status === "done" ? 1 : j.progress} max={1} />
                    <small>{{ uploading: "Đang tải lên", transcribing: "Đang chép lời", done: "Xong", error: j.error }[j.status]}</small>
                  </li>
                ))}
              </ul>
            )}
            <label className="vi-label">Bản chép lời (sửa được)</label>
            <textarea className="vi-text" value={transcript} onChange={(e) => { setTranscript(e.target.value); if (source !== "live" && source !== "file") setSource("text"); }}
              placeholder="Chữ sẽ hiện ở đây khi bạn nói, hoặc dán nội dung vào" rows={8} />
            {partial && <div className="vi-partial">{partial}…</div>}
            <p className="vi-note">Âm thanh chỉ gửi tới máy chủ Legal Agentic để chép lời, chưa lưu lại. Bước sau bạn chọn phần cần làm mờ.</p>
            <div className="vi-actions">
              <button className="vi-btn primary" data-tour="voice-next" disabled={!transcript.trim() || recording} onClick={goReview}>Tiếp: chọn phần làm mờ</button>
            </div>
          </div>
        )}

        {step === "review" && (
          <div className="vi-body vi-review">
            <div className="vi-transcript">{highlighted}</div>
            <div className="vi-spans" data-tour="voice-spans">
              {spans.length === 0 && <p>Không thấy thông tin nhạy cảm. Bạn vẫn có thể sửa nội dung ở bước trước.</p>}
              {Object.entries(grouped).map(([g, list]) => (
                <section key={g}>
                  <h4>{GROUPS[g] || g} ({list.length})</h4>
                  {list.map((s) => {
                    const act = decisions[s.id]?.action || s.default;
                    return (
                      <div key={s.id} className="vi-span">
                        <div className="vi-span-text">“{s.text}”</div>
                        <div className="vi-span-ctrl">
                          {(s.type === "TÌNH_TIẾT" ? ["generalize", "keep"] : ["pseudonym", "keep"]).map((a) => (
                            <label key={a}><input type="radio" name={s.id} checked={act === a} onChange={() => setAction(s, a)} /> {ACTION_LABEL[a]}</label>
                          ))}
                          {act !== "keep" && s.type !== "TÌNH_TIẾT" && (
                            <input className="vi-repl" value={decisions[s.id]?.replacement ?? s.suggestion} onChange={(e) => setRepl(s, e.target.value)} aria-label="Tên thay thế" />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </section>
              ))}
            </div>
            <label className="vi-label">Bản sẽ được gửi</label>
            <div className="vi-preview">{preview}</div>
            {kept > 0 && <p className="vi-warn">Bạn giữ nguyên {kept} đoạn nhạy cảm: bản này chỉ được xử lý trong máy chủ Legal Agentic, không gửi tới AI bên ngoài, và không dùng làm dữ liệu huấn luyện.</p>}
            <div className="vi-actions">
              <button className="vi-btn" onClick={() => setStep("capture")}>Quay lại</button>
              <button className="vi-btn primary" onClick={() => setStep("consent")}>Tiếp: đồng ý</button>
            </div>
          </div>
        )}

        {step === "consent" && (
          <div className="vi-body" data-tour="voice-consent">
            <label className="vi-check"><input type="checkbox" checked={consentCase} onChange={(e) => setConsentCase(e.target.checked)} />
              Tôi đồng ý cho Legal Agentic dùng bản đã làm mờ ở trên để xử lý vụ việc và lập hồ sơ.</label>
            <label className={`vi-check ${kept ? "disabled" : ""}`}><input type="checkbox" disabled={kept > 0} checked={consentTrain && kept === 0} onChange={(e) => setConsentTrain(e.target.checked)} />
              Tôi đồng ý góp bản đã làm mờ (không còn thông tin nhạy cảm) vào dữ liệu cải thiện trợ lý.
              {kept > 0 && <small> Không áp dụng vì bạn giữ nguyên đoạn nhạy cảm.</small>}</label>
            <p className="vi-note">Bản gốc và các giá trị đã làm mờ không được lưu. Bạn có thể đóng cửa sổ này để không gửi gì.</p>
            <div className="vi-actions">
              <button className="vi-btn" onClick={() => setStep("review")}>Quay lại</button>
              <button className="vi-btn primary" disabled={!consentCase} onClick={submit}>Lưu vào hồ sơ</button>
            </div>
          </div>
        )}

        {step === "saved" && saved && (
          <div className="vi-body">
            <p>Đã lưu hồ sơ <code>{saved.intake_id}</code>{saved.consent_training ? ", có góp vào dữ liệu cải thiện" : ""}.</p>
            <div className="vi-preview">{saved.text}</div>
            <AnalysisView intakeId={saved.intake_id} />
            <div className="vi-actions">
              {saved.data_class === "C" && (
                <button className="vi-btn primary" onClick={() => { onUseText(saved.text); reset(); onClose(); }}>Hỏi trợ lý với nội dung này</button>
              )}
              <button className="vi-btn" onClick={() => { reset(); onClose(); }}>Đóng</button>
            </div>
          </div>
        )}

        {error && <p className="vi-error">{error}</p>}
      </div>
    </div>
  );
}

type Unit = {
  domain: string; legal_question: string; facts: string[];
  citations: { doc: string; article: string; status: string }[];
  suggestions: { text: string; needs_lawyer_review: boolean }[];
};
const CITE_MARK: Record<string, string> = {
  verified_in_corpus: "✔ trong kho", in_corpus_pending_approval: "⏳ chờ duyệt", outside_corpus_unverified: "✖ cần kiểm",
};

/** Kết quả phân tích v2.1 của hồ sơ: hỏi lại máy chủ mỗi 5 s, tối đa 3 phút. */
function AnalysisView({ intakeId }: { intakeId: string }) {
  const [state, setState] = useState<{ status: string; units: Unit[] }>({ status: "new", units: [] });
  useEffect(() => {
    let tries = 0;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      const r = await apiFetch(`/api/intake/${intakeId}`).catch(() => null);
      if (r?.ok) {
        const b = await r.json();
        setState({ status: b.status, units: b.analysis?.units || [] });
        if (b.status !== "new") return;
      }
      if (++tries < 36) setTimeout(tick, 5000);
    };
    tick();
    return () => { stop = true; };
  }, [intakeId]);

  if (state.status === "new") return <p className="vi-note">Đang phân tích hồ sơ (tình tiết, câu hỏi pháp lý, điều luật)…</p>;
  if (state.status === "failed" || !state.units.length) return <p className="vi-note">Chưa phân tích được hồ sơ này; luật sư sẽ xem trực tiếp.</p>;
  return (
    <div className="vi-analysis">
      <strong>Phân tích sơ bộ (chờ luật sư duyệt)</strong>
      {state.units.map((u, i) => (
        <div key={i} className="vi-span">
          <div><b>{u.legal_question || "Câu hỏi chưa rõ"}</b> <small>· {u.domain}</small></div>
          {u.facts.length > 0 && <div className="vi-note">Tình tiết: {u.facts.join(" ")}</div>}
          {u.citations.map((c, j) => <div key={j}>{CITE_MARK[c.status] || c.status} — {c.doc} {c.article}</div>)}
          {u.suggestions.slice(0, 3).map((s, j) => <div key={`s${j}`}>Gợi ý: {s.text}</div>)}
        </div>
      ))}
    </div>
  );
}
