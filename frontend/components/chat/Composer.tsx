import { useState } from "react";

import { IconSend } from "@/components/chat/icons";
import VoiceIntake from "@/components/voice/VoiceIntake";
import { lastAnswerUsedUploads, setUseUploads } from "@/lib/chat/useChat";
import { estimateTokens } from "@/lib/chat/storage";

export default function Composer({ value, placeholder, onChange, onSubmit, busy }: {
  value: string;
  placeholder: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  const words = value.trim().split(/\s+/).filter(Boolean).length;
  // tắt mặc định, chỉ nhớ trong phiên trang
  const [useUploads, setLocalUseUploads] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [dropped, setDropped] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);

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
      <div className="composer">
        <div className="composer-tools">
          <button className="tool-btn" data-tour="mic" onClick={() => setVoiceOpen(true)} aria-label="Ghi âm hoặc đính kèm ghi âm" title="Ghi âm / đính kèm ghi âm, video">🎙</button>
        </div>
        <div className="box" data-tour="composer">
          <textarea
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
            rows={1}
          />
          {value.trim().length > 0 && (
            <div className="token-counter">
              {words} từ · ~{estimateTokens(value)} token
            </div>
          )}
        </div>
        <button className="send" onClick={onSubmit} disabled={busy} aria-label="Gửi">
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
