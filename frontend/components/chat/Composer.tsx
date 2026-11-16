import { useState } from "react";

import { IconSend } from "@/components/chat/icons";
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

  return (
    <div className="composer-wrap">
      <div className="composer">
        <div className="box">
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
