/* Hội thoại lưu trong localStorage, tối đa 30 cái gần nhất.

Chỉ lưu khi đã đăng nhập (khách vãng lai giữ hội thoại trong bộ nhớ); mỗi tài khoản
một ngăn riêng để không lẫn lịch sử của nhau (AUTH1).
*/
import type { Conversation } from "@/lib/chat/types";
import type { Mode } from "@/lib/mode";

const MAX_CONVERSATIONS = 30;
// each mode keeps its own history, so interview chats never show up under the law assistant
const storeKey = (mode: Mode, username: string) =>
  `${mode === "pv" ? "llv_conversations_pv" : "llv_conversations"}:${username}`;

export function loadConvos(mode: Mode = "law", username?: string | null): Conversation[] {
  if (!username) return [];
  try {
    const raw = localStorage.getItem(storeKey(mode, username));
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function saveConvos(c: Conversation[], mode: Mode = "law", username?: string | null) {
  if (!username) return;
  try {
    localStorage.setItem(storeKey(mode, username), JSON.stringify(c.slice(0, MAX_CONVERSATIONS)));
  } catch {
    /* storage blocked or full: the conversation just isn't kept */
  }
}

export function genId(): string {
  try { return crypto.randomUUID().replace(/-/g, "").slice(0, 12); }
  catch { return Math.random().toString(16).slice(2, 14); }
}

/** Ước lượng token tiếng Việt: ~1.3 token/từ */
export function estimateTokens(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.ceil(words * 1.3);
}
