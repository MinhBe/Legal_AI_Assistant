"use client";

/* Trang /pv: chat phỏng vấn kỹ thuật ẩn (chỉ mở khi gõ /pv trong ô chat).
   AI đóng vai người phỏng vấn, hỏi câu từ thư viện, đánh giá câu trả lời.
   Endpoint: POST /api/pv/chat (SSE). */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { apiFetch } from "@/lib/api";


/* nhóm câu hỏi (khớp với G-prefix trong thư viện) */
const GROUPS = [
  { id: "", label: "Ngẫu nhiên" },
  { id: "G00", label: "Dự án của Minh" },
  { id: "G01", label: "LLM nền tảng" },
  { id: "G03", label: "Kiến trúc Agent" },
  { id: "G04", label: "Độ tin cậy" },
  { id: "G05", label: "Giao tiếp" },
  { id: "G06", label: "RAG" },
  { id: "G07", label: "Knowledge Graph" },
  { id: "G08", label: "Fullstack" },
  { id: "G09", label: "Đánh giá (Eval)" },
  { id: "G10", label: "Bảo mật" },
  { id: "G11", label: "Vận hành" },
  { id: "G12", label: "Hạ tầng" },
  { id: "G13", label: "Thiết kế hệ thống" },
];

type Msg = { role: "user" | "ai"; content: string };

function useInterview() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function reset() {
    abortRef.current?.abort();
    setMsgs([]);
    setBusy(false);
    setSystemPrompt(null);
  }

  async function send(
    message: string,
    group: string | null,
    n: number,
  ) {
    if (busy) return;
    setBusy(true);

    const userMsg: Msg = { role: "user", content: message };
    const aiMsg: Msg = { role: "ai", content: "" };
    setMsgs((prev) => [...prev, userMsg, aiMsg]);

    const history = msgs.map((m) => ({ role: m.role === "ai" ? "assistant" : "user", content: m.content }));

    abortRef.current = new AbortController();

    try {
      const res = await apiFetch(`/api/pv/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortRef.current.signal,
        body: JSON.stringify({
          message,
          history,
          system_prompt: systemPrompt,
          group: group || null,
          n,
        }),
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";

      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });

        let sep: number;
        while ((sep = buf.indexOf("\n\n")) !== -1) {
          const block = buf.slice(0, sep);
          buf = buf.slice(sep + 2);

          let event = "message";
          const dataLines: string[] = [];
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;
          let data: any;
          try { data = JSON.parse(dataLines.join("\n")); } catch { continue; }

          if (event === "system") {
            setSystemPrompt(data.prompt);
          } else if (event === "token") {
            setMsgs((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.role === "ai") next[next.length - 1] = { ...last, content: last.content + data.text };
              return next;
            });
          }
        }
      }
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        setMsgs((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === "ai") next[next.length - 1] = { ...last, content: "Lỗi kết nối API. Kiểm tra backend đang chạy." };
          return next;
        });
      }
    } finally {
      setBusy(false);
    }
  }

  return { msgs, busy, systemPrompt, send, reset };
}

export default function PvPage() {
  const { msgs, busy, systemPrompt, send, reset } = useInterview();
  const [started, setStarted] = useState(false);
  const [group, setGroup] = useState("");
  const [n, setN] = useState(5);
  const [input, setInput] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  /* auto-scroll xuống khi có tin mới */
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);

  async function start() {
    setStarted(true);
    await send("Bắt đầu", group, n);
  }

  async function submit() {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    await send(q, group, n);
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  };

  if (!started) {
    return (
      <div className="pv-shell">
        <header className="header">
          <Link href="/" className="graph-nav-btn" title="Về trang chat">←</Link>
          <span className="title">Luyện phỏng vấn</span>
        </header>
        <div className="pv-start">
          <h2 className="pv-start-title">Chọn nhóm câu hỏi</h2>
          <p className="pv-start-sub">
            AI sẽ hỏi {n} câu, đánh giá từng câu trả lời, và tổng kết buổi phỏng vấn.
          </p>

          <div className="pv-chips" style={{ justifyContent: "center" }}>
            {GROUPS.map((g) => (
              <button key={g.id} className={`pv-chip${group === g.id ? " on" : ""}`}
                onClick={() => setGroup(g.id)}>
                {g.label}
              </button>
            ))}
          </div>

          <div className="pv-start-row">
            <label className="pv-start-label">
              Số câu:
              <select className="pv-select" value={n} onChange={(e) => setN(Number(e.target.value))}>
                {[3, 5, 8, 10].map((v) => <option key={v} value={v}>{v} câu</option>)}
              </select>
            </label>
            <button className="pv-btn" onClick={start}>Bắt đầu phỏng vấn →</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="pv-shell">
      <header className="header">
        <Link href="/" className="graph-nav-btn" title="Về trang chat">←</Link>
        <span className="title">Luyện phỏng vấn</span>
        <button className="pv-btn pv-btn-ghost" style={{ fontSize: 12 }}
          onClick={() => { reset(); setStarted(false); }}>
          Buổi mới
        </button>
      </header>

      <div className="pv-chat-body" ref={listRef}>
        {msgs.map((m, i) => (
          <div key={i} className={`pv-chat-msg pv-chat-${m.role}`}>
            <div className="pv-chat-bubble">
              {m.role === "ai"
                ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || "…"}</ReactMarkdown>
                : <p>{m.content}</p>}
            </div>
          </div>
        ))}
        {busy && msgs[msgs.length - 1]?.role !== "ai" && (
          <div className="pv-chat-msg pv-chat-ai">
            <div className="pv-chat-bubble pv-chat-typing">…</div>
          </div>
        )}
      </div>

      <div className="pv-chat-composer">
        <textarea
          className="pv-chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Nhập câu trả lời… (Enter để gửi, Shift+Enter xuống dòng)"
          rows={3}
          disabled={busy}
        />
        <button className="pv-btn" onClick={submit} disabled={busy || !input.trim()}>
          Gửi
        </button>
      </div>
    </div>
  );
}
