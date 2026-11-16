"use client";

/* Toàn bộ logic của khung chat: hội thoại đang mở, danh sách hội thoại đã lưu,
   gửi câu hỏi qua SSE, đồng bộ ?t=<id> trên URL, phê duyệt khi từ chối, và
   gợi ý câu hỏi chuẩn hơn. Component chỉ hiển thị và gọi các hàm này. */
import { useEffect, useRef, useState } from "react";

import { genId, loadConvos, saveConvos } from "@/lib/chat/storage";
import type { Conversation, Msg, Section, TimeFrame } from "@/lib/chat/types";
import type { Mode } from "@/lib/mode";
import { streamChat } from "@/lib/sse";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";
const REFUSAL = "Không đủ căn cứ trong kho văn bản để trả lời chắc chắn câu này.";
const ESCALATION_POLL_MS = 10_000;

// deferred: replaceState during render makes the Next router warn
function setUrl(id: string | null) {
  const url = id ? `/?t=${id}` : "/";
  setTimeout(() => window.history.replaceState(null, "", url), 0);
}

export function useChat(mode: Mode = "law") {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const threadId = useRef<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // switching mode opens that mode's own history, starting from an empty chat
  useEffect(() => {
    const saved = loadConvos(mode);
    setConvos(saved);
    setMessages([]);
    setActiveId(null);
    threadId.current = null;
    // reopen the conversation named in the URL, so a reload lands where it was
    try {
      const tid = new URLSearchParams(window.location.search).get("t");
      const match = tid ? saved.find((c) => c.id === tid) : undefined;
      if (match) {
        setMessages(match.messages);
        setActiveId(match.id);
        threadId.current = match.id;
      }
    } catch { /* ignore */ }
  }, [mode]);

  function scrollDown() {
    requestAnimationFrame(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight }));
  }

  function newChat() {
    setMessages([]);
    setActiveId(null);
    threadId.current = null;
    setUrl(null);
  }

  function openConvo(c: Conversation) {
    setMessages(c.messages);
    setActiveId(c.id);
    threadId.current = c.id;
    setUrl(c.id);
    scrollDown();
  }

  function deleteConvo(id: string) {
    setConvos((prev) => {
      const next = prev.filter((x) => x.id !== id);
      saveConvos(next, mode);
      return next;
    });
    if (activeId === id) newChat();
  }

  function persist(msgs: Msg[]) {
    const id = threadId.current || genId();
    threadId.current = id;
    setUrl(id);
    const title = msgs.find((m) => m.role === "user")?.content.slice(0, 48) || "Cuộc trò chuyện";
    setConvos((prev) => {
      const rest = prev.filter((c) => c.id !== id);
      const next = [{ id, title, messages: msgs }, ...rest];
      saveConvos(next, mode);
      return next;
    });
    setActiveId(id);
  }

  // saved right away, so a reload keeps the approval state of the card
  const patchMessage = (idx: number, patch: Partial<Msg>) =>
    setMessages((msgs) => {
      const next = msgs.map((m, i) => (i === idx ? { ...m, ...patch } : m));
      persist(next);
      return next;
    });

  async function escalate(question: string, msgIdx: number) {
    try {
      const res = await fetch(`${API_BASE}/api/escalate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, thread_id: threadId.current }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      patchMessage(msgIdx, { escalate_id: data.id, escalate_status: "waiting" });
    } catch {
      // not sent: the card stays on its buttons so the user can try again
      patchMessage(msgIdx, { escalate_status: "pending" });
    }
  }

  /* cards waiting for the expert ask the API again until a human has decided */
  const waitingKey = messages
    .map((m, i) => (m.escalate_id && (m.escalate_status === "waiting" || m.escalate_status === "approved") ? `${i}:${m.escalate_id}` : ""))
    .filter(Boolean).join(",");
  useEffect(() => {
    if (!waitingKey) return;
    const check = () => waitingKey.split(",").forEach(async (pair) => {
      const [idx, id] = pair.split(":");
      try {
        const r = await fetch(`${API_BASE}/api/escalations/${id}`);
        if (!r.ok) return;
        const e = await r.json();
        if (e.status === "approved") patchMessage(+idx, { escalate_status: "answered", escalate_reply: e.reply });
        else if (e.status === "denied") patchMessage(+idx, { escalate_status: "rejected", escalate_reply: e.reply });
      } catch { /* API down: try again on the next tick */ }
    });
    check();
    const t = setInterval(check, ESCALATION_POLL_MS);
    return () => clearInterval(t);
  }, [waitingKey]);

  const denyEscalate = (msgIdx: number) => patchMessage(msgIdx, { escalate_status: "denied" });
  const ignoreSuggestion = (msgIdx: number) => patchMessage(msgIdx, { suggested_query: undefined });

  /** Gửi câu hỏi. Trả về false khi bỏ qua (rỗng hoặc đang chờ câu trước). */
  function send(text: string): boolean {
    const q = text.trim();
    if (!q || busy) return false;
    void run(q);
    return true;
  }

  function applySuggestion(msgIdx: number, suggested: string): boolean {
    patchMessage(msgIdx, { suggest_used: true });
    return send(suggested);
  }

  async function run(q: string) {
    setBusy(true);

    const history = messages.map((m) => ({ role: m.role === "ai" ? "assistant" : "user", content: m.content }));
    // append to the latest state, not this render's snapshot: a patch made just
    // before sending (suggest_used on "Dùng câu này") would otherwise be lost
    setMessages((prev) => [
      ...prev,
      { role: "user", content: q },
      { role: "ai", content: "", steps_log: [] },
    ]);
    scrollDown();

    // Cập nhật BẤT BIẾN: luôn tạo object mới, không mutate.
    const update = (fn: (ai: Msg) => Msg) =>
      setMessages((m) => m.map((x, i) => (i === m.length - 1 && x.role === "ai" ? fn(x) : x)));

    try {
      await streamChat(API_BASE, { message: q, thread_id: threadId.current, history, mode }, (event, data) => {
        if (event === "start") threadId.current = threadId.current || data.thread_id;
        else if (event === "step")
          update((ai) => ({
            ...ai,
            step: data.label,
            steps_log: [...(ai.steps_log ?? []), data.label],
          }));
        else if (event === "token") update((ai) => ({ ...ai, content: ai.content + (data.text ?? "") }));
        else if (event === "citation")
          update((ai) => ({ ...ai, citations: [...(ai.citations ?? []), data] }));
        else if (event === "section")
          update((ai) => ({ ...ai, sections: [...(ai.sections ?? []), data as Section] }));
        else if (event === "timeframe")
          update((ai) => ({ ...ai, timeframe: data as TimeFrame }));
        else if (event === "suggest_rewrite")
          update((ai) => ({ ...ai, suggested_query: data.suggested, suggest_reason: data.reason }));
        else if (event === "error") update((ai) => ({ ...ai, content: ai.content + `\n\n⚠️ ${data.message}` }));
        else if (event === "done") {
          update((ai) => {
            // escalate: backend asks for the expert-approval card (questions outside the corpus)
            const isRefusal = ai.content.trim().startsWith(REFUSAL.slice(0, 20)) || !!data?.escalate;
            return {
              ...ai,
              step: undefined,
              refusal: isRefusal,
              escalate_status: isRefusal ? "pending" : null,
            };
          });
        }
        scrollDown();
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Lỗi không xác định";
      update((ai) => ({ ...ai, content: ai.content + `\n\n⚠️ Lỗi kết nối: ${msg}` }));
    } finally {
      setBusy(false);
      setMessages((m) => {
        const copy = m.map((x) => ({ ...x, step: undefined }));
        persist(copy);
        return copy;
      });
    }
  }

  return {
    messages, convos, activeId, busy, threadId, listRef,
    newChat, openConvo, deleteConvo, send, escalate, denyEscalate, applySuggestion, ignoreSuggestion,
  };
}

export type ChatState = ReturnType<typeof useChat>;

/* chế độ sáng / tối: mặc định theo hệ điều hành, nhớ lựa chọn tay */
export function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark" | "system">("system");

  useEffect(() => {
    try {
      const saved = localStorage.getItem("llv_theme") as "light" | "dark" | "system" | null;
      if (saved && saved !== "system") {
        setTheme(saved);
        document.documentElement.setAttribute("data-theme", saved);
      }
    } catch { /* ignore */ }
  }, []);

  function toggleTheme() {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("llv_theme", next); } catch { /* ignore */ }
      return next;
    });
  }

  return { theme, toggleTheme };
}
