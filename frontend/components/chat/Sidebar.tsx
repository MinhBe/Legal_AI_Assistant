import Link from "next/link";
import { useEffect, useState } from "react";

import { IconDash, IconGraph, IconPlus, IconSearch } from "@/components/chat/icons";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";
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
  const { user, can, logout } = useAuth();
  const tag = user.role === "dev" ? "DEV" : user.username === "guest1" ? "VIP" : null;
  const canReview = can("review");
  // LI2b: số tin ảnh hưởng cao mới hơn mốc đã xem (mốc lưu ở máy khách lúc mở /tin-moi)
  const [unseen, setUnseen] = useState(0);

  useEffect(() => {
    if (!canReview) return;
    let alive = true;
    apiFetch("/api/intel/alerts")
      .then((res) => (res.ok ? res.json() : null))
      .then((body) => {
        if (!alive) return;
        const seen = localStorage.getItem("intel_seen_at") ?? "";
        const rows: { created_at: string | null }[] = Array.isArray(body?.items) ? body.items : [];
        setUnseen(rows.filter((row) => !seen || (row.created_at ?? "") > seen).length);
      })
      .catch(() => undefined);
    return () => { alive = false; };
  }, [canReview]);

  return (
    <aside data-tour="sidebar" className={`sidebar ${open ? "" : "closed"}`}>
      <div className="brand">
        <div className="logo">L</div>
        <div>
          <div className="name">{text.brand}</div>
          <div className="sub">{text.brandSub}</div>
        </div>
      </div>

      {/* AUTH1: ai đang dùng, và còn bao nhiêu câu trong ngày */}
      <div className="auth-user">
        {user.username ? (
          <>
            <span className="auth-who">
              {user.username}
              <span className="auth-role">{user.role}</span>
              {tag && <b className={`auth-tag ${tag === "VIP" ? "vip" : ""}`}>{tag}</b>}
            </span>
            <button className="auth-logout" onClick={logout}>Đăng xuất</button>
          </>
        ) : (
          <Link href="/login" className="auth-login-btn">Đăng nhập</Link>
        )}
        {user.remaining !== null && <div className="auth-quota">Còn {user.remaining} câu hôm nay</div>}
        {!user.username && (
          <div className="auth-banner">Khách vãng lai: lịch sử không được lưu</div>
        )}
      </div>

      <button className="new-chat" onClick={onNew}>
        <IconPlus /> Cuộc trò chuyện mới
      </button>

      <div className="side-quick-links">
        {can("graph") && (
          <Link href="/graph" className="side-quick-btn">
            <IconGraph /> Knowledge Graph
          </Link>
        )}
        {can("review") && (
          <Link href="/dashboard" className="side-quick-btn">
            <IconDash /> Dashboard
          </Link>
        )}
        {can("review") && (
          <Link href="/tin-moi" className="side-quick-btn">
            <IconSearch /> Tin pháp luật mới
            {unseen > 0 && (
              <span className="intel-badge" title={`${unseen} tin ảnh hưởng cao chưa xem`}>
                {unseen}
              </span>
            )}
          </Link>
        )}
        {can("review") && (
          <Link href="/bai-toan" className="side-quick-btn">
            <IconSearch /> Bài toán
          </Link>
        )}
        {(can("upload") || canReview) && (
          <Link href="/bieu-mau" className="side-quick-btn">
            <IconSearch /> Biểu mẫu
          </Link>
        )}
        <Link href="/tinh" className="side-quick-btn">
          Máy tính
        </Link>
        <Link href="/ra-soat-hop-dong" className="side-quick-btn">
          Rà soát hợp đồng
        </Link>
        <Link href="/theo-doi" className="side-quick-btn">
          Theo dõi luật mới
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
