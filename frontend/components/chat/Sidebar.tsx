import Link from "next/link";

import { IconDash, IconGraph, IconPlus } from "@/components/chat/icons";
import type { Conversation } from "@/lib/chat/types";
import type { MODE_TEXT } from "@/lib/mode";

export default function Sidebar({ open, text, convos, activeId, onNew, onOpen, onDelete }: {
  open: boolean;
  text: (typeof MODE_TEXT)["law"];
  convos: Conversation[];
  activeId: string | null;
  onNew: () => void;
  onOpen: (c: Conversation) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className={`sidebar ${open ? "" : "closed"}`}>
      <div className="brand">
        <div className="logo">L</div>
        <div>
          <div className="name">{text.brand}</div>
          <div className="sub">{text.brandSub}</div>
        </div>
      </div>

      <button className="new-chat" onClick={onNew}>
        <IconPlus /> Cuộc trò chuyện mới
      </button>

      <div className="side-quick-links">
        <Link href="/graph" className="side-quick-btn">
          <IconGraph /> Knowledge Graph
        </Link>
        <Link href="/dashboard" className="side-quick-btn">
          <IconDash /> Dashboard
        </Link>
        <Link href="/tinh" className="side-quick-btn">
          Máy tính
        </Link>
      </div>

      <div className="side-label">Gần đây</div>
      <div className="thread-list">
        {convos.length === 0 && <div className="thread-empty">Chưa có cuộc trò chuyện nào.</div>}
        {convos.map((c) => (
          <div key={c.id} className={`thread-item ${c.id === activeId ? "active" : ""}`} title={c.title}>
            <span className="thread-title" onClick={() => onOpen(c)}>{c.title}</span>
            <button
              className="thread-del"
              title="Xóa cuộc trò chuyện"
              onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
            >···</button>
          </div>
        ))}
      </div>

      <div className="side-foot">
        {text.source}
      </div>
    </aside>
  );
}
