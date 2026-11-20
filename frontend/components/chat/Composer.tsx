import { useRef, useState } from "react";

import SendReview, { detectSpans, type Span } from "@/components/chat/SendReview";
import { IconSend } from "@/components/chat/icons";
import { emit } from "@/components/help/Coach";
import VoiceIntake from "@/components/voice/VoiceIntake";
import { lastAnswerUsedUploads, setUseUploads } from "@/lib/chat/useChat";
import { estimateTokens } from "@/lib/chat/storage";
import { LiveMic, type SttEvent } from "@/lib/voice/mic";

/* Ô hỏi kiểu ChatGPT: 🎙 cạnh nút Gửi đọc thẳng vào ô (chèn tại con trỏ; dừng, gõ tay, nói tiếp),
   chữ tạm màu xám ngay dưới ô; bấm Gửi mới làm mờ (chỉ khi có đoạn nhạy cảm). 📎: tệp ghi âm/video. */
export default function Composer({ value, placeholder, onChange, onSubmit, onSend, busy }: {
  value: string;
  placeholder: string;
  onChange: (v: string) => void;
  onSubmit?: () => void;
  onSend?: (text: string) => void;
  busy: boolean;
}) {
  const words = value.trim().split(/\s+/).filter(Boolean).length;
  const [useUploads, setLocalUseUploads] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [dropped, setDropped] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [dictating, setDictating] = useState(false);
  const [partial, setPartial] = useState("");
  const [micError, setMicError] = useState("");
  const [review, setReview] = useState<{ text: string; spans: Span[] } | null>(null);
  const [checking, setChecking] = useState(false);
  const ta = useRef<HTMLTextAreaElement>(null);
  const mic = useRef<LiveMic | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  const cursor = useRef<number | null>(null);

  const send = (text: string) => {
    if (onSend) onSend(text);
    else { onChange(text); onSubmit?.(); }
  };

  /** chèn câu đã chốt vào đúng chỗ con trỏ (nhớ vị trí lúc bấm micro / lúc gõ) */
  const insertFinal = (t: string) => {
    if (!t) return;
    const v = valueRef.current;
    const at = Math.min(cursor.current ?? v.length, v.length);
    const before = v.slice(0, at), after = v.slice(at);
    const sep = before && !/\s$/.test(before) ? " " : "";
    const next = before + sep + t + (after && !/^\s/.test(after) ? " " : "") + after;
    cursor.current = (before + sep + t).length;
    onChange(next);
  };

  const onEvent = (e: SttEvent) => {
    if (e.type === "partial") setPartial(e.text || "");
    if (e.type === "final") { setPartial(""); insertFinal(e.text || ""); }
    if (e.type === "error") { setMicError(e.text || "Lỗi chép lời"); setDictating(false); }
  };

  const toggleMic = async () => {
    setMicError("");
    if (dictating) {
      setDictating(false);
      await mic.current?.stop();
      setTimeout(() => { mic.current?.close(); setPartial(""); }, 4000);
      return;
    }
    cursor.current = ta.current?.selectionStart ?? valueRef.current.length;
    try {
      mic.current = new LiveMic(onEvent);
      await mic.current.start();
      setDictating(true);
      emit("dictation-started");
    } catch {
      setMicError("Không mở được micro hoặc máy chủ chép lời");
    }
  };

  const submit = async () => {
    const text = value.trim();
    if (!text || busy || checking) return;
    if (dictating) await toggleMic();
    setChecking(true);
    const spans = await detectSpans(text);
    setChecking(false);
    if (spans.length) { setReview({ text, spans }); emit("review-shown"); }
    else send(text);
  };

  return (
    <div className={`composer-wrap ${drag ? "drag" : ""}`}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDrag(true); } }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        if (!e.dataTransfer.files.length) return;
        e.preventDefault(); setDrag(false);
        setDropped(Array.from(e.dataTransfer.files)); setVoiceOpen(true);
      }}>
      <VoiceIntake open={voiceOpen} initialFiles={dropped}
        onClose={() => { setVoiceOpen(false); setDropped([]); }}
        onUseText={(t) => onChange(t)} />
      {review && (
        <SendReview text={review.text} spans={review.spans} onCancel={() => setReview(null)}
          onSend={(t) => { setReview(null); send(t); }} />
      )}
      <div className="composer">
        <div className="composer-tools">
          <button className="tool-btn" data-tour="attach" onClick={() => setVoiceOpen(true)}
            aria-label="Đính kèm ghi âm hoặc video" title="Đính kèm tệp ghi âm / video (hoặc kéo thả vào đây)">📎</button>
        </div>
        <div className="box" data-tour="composer">
          <textarea
            ref={ta}
            value={value}
            placeholder={dictating ? "Đang nghe… nói tiếp hoặc bấm micro để dừng và gõ tay" : placeholder}
            onChange={(e) => { onChange(e.target.value); cursor.current = e.target.selectionStart; }}
            onSelect={(e) => { cursor.current = (e.target as HTMLTextAreaElement).selectionStart; }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
            rows={1}
          />
          {partial && <div className="dictation-partial" aria-live="polite">{partial}…</div>}
          {micError && <div className="dictation-error">{micError}</div>}
          {value.trim().length > 0 && !partial && (
            <div className="token-counter">
              {words} từ · ~{estimateTokens(value)} token
            </div>
          )}
        </div>
        <button className={`mic-btn ${dictating ? "on" : ""}`} data-tour="mic" onClick={toggleMic}
          aria-pressed={dictating} aria-label={dictating ? "Dừng đọc" : "Đọc bằng giọng nói"}
          title={dictating ? "Dừng (bạn có thể gõ tay rồi bấm lại để nói tiếp)" : "Nói, chữ chạy vào ô"}>
          {dictating ? "■" : "🎙"}
        </button>
        <button className="send" onClick={() => void submit()} disabled={busy || checking} aria-label="Gửi">
          <IconSend />
        </button>
      </div>
      <div className="use-uploads">
        <label>
          <input
            type="checkbox"
            checked={useUploads}
            onChange={(e) => {
              setLocalUseUploads(e.target.checked);
              setUseUploads(e.target.checked);
            }}
          />
          Dùng tài liệu đã duyệt (chỉ xử lý trong máy)
        </label>
        {lastAnswerUsedUploads() && (
          <span className="use-uploads-chip">Có dùng tài liệu tải lên — xử lý trong máy</span>
        )}
      </div>
      <div className="hint">Thông tin mang tính tham khảo, luôn đối chiếu văn bản gốc được trích dẫn.</div>
    </div>
  );
}
