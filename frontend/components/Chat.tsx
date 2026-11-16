"use client";

/* Khung chat: lắp thanh bên, danh sách tin nhắn và ô nhập. Logic hội thoại nằm
   ở lib/chat/useChat.ts. */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import Composer from "@/components/chat/Composer";
import { IconGraph, IconMenu, IconMoon, IconSun } from "@/components/chat/icons";
import MessageList from "@/components/chat/MessageList";
import Sidebar from "@/components/chat/Sidebar";
import { useChat, useTheme } from "@/lib/chat/useChat";
import { currentMode, type Mode, MODE_TEXT } from "@/lib/mode";

export default function Chat() {
  const [mode, setMode] = useState<Mode>("law");
  const chat = useChat(mode);
  const { theme, toggleTheme } = useTheme();
  const [input, setInput] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const text = MODE_TEXT[mode];

  useEffect(() => { setMode(currentMode()); }, []);

  const router = useRouter();

  // every accepted question clears the composer, whichever button sent it;
  // "/pv" is not a question: it opens the hidden interview-practice page
  const ask = (q: string) => {
    if (q.trim().toLowerCase() === "/pv") { setInput(""); router.push("/pv"); return; }
    if (chat.send(q)) setInput("");
  };

  return (
    <div className="shell">
      <Sidebar open={sidebarOpen} text={text} convos={chat.convos} activeId={chat.activeId}
        onNew={chat.newChat} onOpen={chat.openConvo} onDelete={chat.deleteConvo} />

      <main className="main">
        <header className="header">
          <button className="icon-btn" onClick={() => setSidebarOpen((v) => !v)} aria-label="Ẩn/hiện thanh bên">
            <IconMenu />
          </button>
          <span className="title">{text.title}</span>
          <Link href="/graph" className="graph-nav-btn" title="Knowledge Graph">
            <IconGraph />
          </Link>
          <Link href="/upload" className="graph-nav-btn" title="Tải tài liệu lên">Tải lên</Link>
          <button className="theme-btn" onClick={toggleTheme} aria-label="Đổi chế độ sáng/tối">
            {theme === "dark" ? <><IconSun /> Sáng</> : <><IconMoon /> Tối</>}
          </button>
        </header>

        <MessageList
          messages={chat.messages} threadId={chat.threadId.current} listRef={chat.listRef} text={text}
          onAsk={ask}
          onUseSuggestion={(i, q) => { if (chat.applySuggestion(i, q)) setInput(""); }}
          onIgnoreSuggestion={chat.ignoreSuggestion}
          onEscalate={chat.escalate}
          onDeny={chat.denyEscalate} />

        <Composer value={input} placeholder={text.placeholder} onChange={setInput} onSubmit={() => ask(input)} busy={chat.busy} />
      </main>
    </div>
  );
}
