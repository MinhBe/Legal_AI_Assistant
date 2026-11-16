"use client";

/* Trạng thái đăng nhập ở trình duyệt (AUTH1): user, login, logout, can(perm).

Quyền thật do máy chủ quyết định; ở đây chỉ để giao diện ẩn/hiện cho khớp.
*/

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { apiFetch, setToken } from "@/lib/api";

export type User = {
  username: string | null;
  role: string;
  perms: string[];
  daily: number | null;
  remaining: number | null;
};

const ANON: User = {
  username: null, role: "anonymous", perms: ["chat", "calc"], daily: 10, remaining: null,
};

type AuthValue = {
  user: User;
  ready: boolean;
  login: (username: string, password: string) => Promise<string | null>;
  logout: () => void;
  can: (perm: string) => boolean;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User>(ANON);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch("/api/auth/me");
      if (r.ok) setUser(await r.json());
    } catch {
      /* API tắt: giữ trạng thái đang có */
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    try {
      const r = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) return typeof body.detail === "string" ? body.detail : "Đăng nhập không thành công";
      setToken(body.token);
      await refresh();
      return null;
    } catch {
      return "Không kết nối được API";
    }
  }, [refresh]);

  const logout = useCallback(() => {
    setToken(null);  // đăng xuất phía máy khách: bỏ token là xong
    void refresh();
  }, [refresh]);

  const can = useCallback((perm: string) => user.perms.includes(perm), [user.perms]);

  return (
    <AuthContext.Provider value={{ user, ready, login, logout, can, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth phải nằm trong <AuthProvider>");
  return ctx;
}

/** Cửa giao diện cho trang chỉ dành cho admin/dev; API vẫn từ chối nếu thiếu quyền. */
export function RequirePerm({ perm, children }: { perm: string; children: React.ReactNode }) {
  const { user, ready, can } = useAuth();
  if (!ready) return null;
  if (can(perm)) return <>{children}</>;
  return (
    <div className="auth-gate">
      <h1 className="auth-gate-title">Trang này chỉ dành cho admin/dev</h1>
      <p className="auth-gate-sub">
        {user.username
          ? `Tài khoản ${user.username} (${user.role}) không có quyền này.`
          : "Bạn chưa đăng nhập, hoặc phiên đã hết hạn."}
      </p>
      <Link href="/login" className="auth-link">Đăng nhập</Link>
    </div>
  );
}
