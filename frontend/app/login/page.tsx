"use client";

/* Đăng nhập tài khoản demo (AUTH1). Mật khẩu = tên đăng nhập: CHỈ dùng trên máy
   nội bộ, xem mục cảnh báo trong README trước khi đưa lên mạng. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/lib/auth";

const DEMO_ACCOUNTS = [
  { username: "admin", role: "admin", note: "toàn quyền" },
  { username: "dev", role: "dev", note: "toàn quyền + công cụ dev" },
  { username: "user1", role: "user", note: "50 câu/ngày, gửi luật sư" },
  { username: "user2", role: "user", note: "như user1" },
  { username: "user3", role: "user", note: "như user1" },
  { username: "guest1", role: "guest_vip", note: "VIP: không giới hạn, ưu tiên đám mây" },
  { username: "guest2", role: "guest", note: "20 câu/ngày" },
  { username: "guest3", role: "guest", note: "như guest2" },
];

export default function LoginPage() {
  const { login, user } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const problem = await login(username.trim(), password);
    setBusy(false);
    if (problem) setError(problem);
    else router.push("/");
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1 className="auth-title">Đăng nhập</h1>
        <p className="auth-sub">
          {user.username ? `Đang đăng nhập: ${user.username} (${user.role})` : "Tài khoản demo của máy nội bộ"}
        </p>

        <label className="auth-label" htmlFor="username">Tên đăng nhập</label>
        <input
          id="username" className="auth-input" value={username} autoComplete="username"
          onChange={(e) => setUsername(e.target.value)}
        />

        <label className="auth-label" htmlFor="password">Mật khẩu</label>
        <input
          id="password" className="auth-input" type="password" value={password}
          autoComplete="current-password" onChange={(e) => setPassword(e.target.value)}
        />

        {error && <p className="auth-error">{error}</p>}

        <button className="auth-submit" type="submit" disabled={busy || !username || !password}>
          {busy ? "Đang kiểm tra…" : "Đăng nhập"}
        </button>

        <div className="auth-hint">
          <strong>Tài khoản demo</strong> (mật khẩu = tên đăng nhập, chỉ dùng nội bộ):
          <ul>
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.username}>
                <code>{a.username}</code> — {a.role}: {a.note}
              </li>
            ))}
          </ul>
        </div>

        <Link href="/" className="auth-link">← Về trang chat</Link>
      </form>
    </div>
  );
}
