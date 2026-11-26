/**
 * free/auto: một model ảo dùng song song mọi model miễn phí (Minh 22/11/2026).
 *
 * Chọn `--model free/auto` (hoặc /model free/auto). Mỗi lượt người dùng hỏi, router lấy model kế tiếp
 * theo vòng trong POOL (Dahl, OpenRouter :free, ScaleRouter), bỏ qua model đang nghỉ, nên nhiều
 * cửa sổ Pi chạy cùng lúc tự chia đều qua các nhà cung cấp. Trong một lượt (sau khi gọi tool) giữ
 * nguyên model để không mất cache. Request lỗi thì model đó nghỉ (429/5xx: 2 phút; 401/402/403/404:
 * 1 giờ) và lần thử lại sang model khác. Key của từng provider vẫn do pi-rr xoay vòng.
 *
 * Đổi danh sách: sửa POOL, hoặc file <pi-dev>/keys/free-auto.models (mỗi dòng "provider/model").
 * Trạng thái nghỉ dùng chung giữa các cửa sổ: keys/.free-auto.json
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const POOL = [
  // ScaleRouter đứng đầu (22/11, key mới): sr-models tự xoay tiếp DeepSeek → beam → mimo → hy4… bên trong ScaleRouter.
  "scalerouter/deepseek-v4.1-flash-free",
  // Ưu tiên model Trung Quốc (Minh 22/11/2026). hy4 và DeepSeek trên OpenRouter là bản trả phí: key or-165 hạn mức 0 USD nên chưa vào được.
  "dahl/deepseek-ai/DeepSeek-V4-Flash-0731",
  "openrouter/baidu/ernie-5.5-flash-preview:free",
  "dahl/zai-org/GLM-5.3-Flash",
  "openrouter/inclusionai/ling-3.2-flash:free",
  "dahl/MiniMaxAI/MiniMax-M2.7",
  // rồi tới model khác đã trả lời đúng câu luật thử (60 ngày) ngày 22/11
  "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
  "openrouter/nvidia/nemotron-3.5-super-vl:free",
  "openrouter/particle-ai/particle-1:free",
  "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
  "openrouter/google/gemma-4-31b-it:free",
];
const COOL_S = 120;
const BLOCK_S = 3600;

const AGENT_DIR = process.env.PI_CODING_AGENT_DIR ?? path.join(os.homedir(), ".pi", "agent");
const KEYS_DIR =
  process.env.PI_KEYS_DIR ??
  [path.resolve(AGENT_DIR, "..", "keys"), path.resolve(AGENT_DIR, "..", "..", "keys")].find((d) => fs.existsSync(d)) ??
  path.resolve(AGENT_DIR, "..", "keys");
const STATE = path.join(KEYS_DIR, ".free-auto.json");
const now = () => Math.floor(Date.now() / 1000);

type State = { next: number; cool: Record<string, number> };

function pool(): string[] {
  try {
    const l = fs.readFileSync(path.join(KEYS_DIR, "free-auto.models"), "utf8").split(/\r?\n/).map((x) => x.trim())
      .filter((x) => x && !x.startsWith("#"));
    if (l.length) return l;
  } catch { /* dùng POOL */ }
  return POOL;
}

function load(): State {
  try {
    const s = JSON.parse(fs.readFileSync(STATE, "utf8"));
    return { next: Number(s.next) || 0, cool: s.cool ?? {} };
  } catch {
    return { next: 0, cool: {} };
  }
}

function save(s: State) {
  try { fs.writeFileSync(STATE, JSON.stringify(s)); } catch { /* bỏ qua */ }
}

// Model ảo: ctx.model của các extension khác là "free/…", không phải provider thật. Ghi provider thật
// vào globalThis để pi-rr (xoay key) và sr-models (xoay model ScaleRouter) biết request đi đâu.
function route(model: any, thinkingLevel: string) {
  (globalThis as any).__piPhysicalProvider = model?.provider;
  return { model, thinkingLevel };
}

const dbg = (m: string) => { if (process.env.FREE_AUTO_DEBUG) process.stderr.write(`${m}\n`); };

const split = (ref: string) => {
  const i = ref.indexOf("/");
  return { provider: ref.slice(0, i), id: ref.slice(i + 1) };
};

export default function (pi: ExtensionAPI) {
  pi.registerVirtualModel({
    provider: "free",
    id: "auto",
    name: "Free auto (Dahl + OpenRouter + ScaleRouter)",
    thinkingLevels: ["low", "medium", "high"],
    contextWindow: 128000,
    route(request: any, ctx: any) {
      const level = request.thinkingLevel ?? "low";
      // trong một lượt (sau tool) giữ model cũ: không mất cache
      if (request.reason === "continuation" && request.previous) {
        return route(request.previous.model, request.previous.thinkingLevel ?? level);
      }
      const s = load();
      if (request.reason === "retry" && request.failed) {
        const m = request.failed.model;
        const code = Number(String(request.failed.message?.errorMessage ?? "").match(/^(\d{3})\b/)?.[1] ?? 0);
        // OpenRouter 429 là giới hạn theo key: pi-rr đã cho key đó nghỉ, giữ model để key khác gánh
        if (!(m.provider === "openrouter" && code === 429))
          s.cool[`${m.provider}/${m.id}`] = now() + ([401, 402, 403, 404].includes(code) ? BLOCK_S : COOL_S);
      }
      const list = pool();
      for (let step = 0; step < list.length; step++) {
        const ref = list[(s.next + step) % list.length];
        if ((s.cool[ref] ?? 0) > now()) continue;
        const { provider, id } = split(ref);
        if ((globalThis as any).__piKeysLeft?.(provider) === 0) continue; // provider hết key hôm nay
        const model = ctx.modelRegistry.find(provider, id);
        if (!model) continue;
        s.next = (s.next + step + 1) % list.length;
        save(s);
        if (process.env.FREE_AUTO_DEBUG) process.stderr.write(`free/auto -> ${ref}\n`);
        return route(model, level);
      }
      save(s);
      throw new Error("free/auto: mọi model miễn phí đang nghỉ; thử lại sau ít phút");
    },
  });

  // Model ưu tiên theo vai (Minh 22–23/11/2026). Không xoay theo lượt: luôn dùng model đầu tiên còn dùng
  // được trong danh sách; lỗi/giới hạn thì nghỉ và rơi xuống model kế tiếp.
  //   free/dev    : dev chính, model miễn phí
  //   free/lead   : Codex qua gói ChatGPT (openai-codex) → hết Codex thì model miễn phí mạnh nhất
  //   free/review : như lead nhưng thứ tự khác, để reviewer ít khi trùng model với dev/lead
  for (const [id, list, name] of [
    ["dev", DEV, "Free dev (ScaleRouter → OpenRouter → DeepSeek)"],
    ["lead", LEAD, "Lead (Codex subscription → free fallback)"],
    ["review", REVIEW, "Review (Codex subscription → free fallback)"],
  ] as [string, string[], string][]) {
    pi.registerVirtualModel({
      provider: "free",
      id,
      name,
      thinkingLevels: ["low", "medium", "high"],
      contextWindow: 128000,
      route(request: any, ctx: any) {
        const level = request.thinkingLevel ?? (id === "dev" ? "low" : "medium");
        if (request.reason === "continuation" && request.previous) {
          return route(request.previous.model, request.previous.thinkingLevel ?? level);
        }
        const s = load();
        if (request.reason === "retry" && request.failed) {
          const m = request.failed.model;
          const code = Number(String(request.failed.message?.errorMessage ?? "").match(/^(\d{3})\b/)?.[1] ?? 0);
          // OpenRouter 429 là giới hạn theo key: pi-rr đã cho key đó nghỉ, giữ model để key khác gánh.
          // Codex (gói ChatGPT) 429 = hết hạn mức gói, thường vài giờ mới hồi: nghỉ lâu.
          if (!(m.provider === "openrouter" && code === 429)) {
            const long = [400, 401, 402, 403, 404].includes(code) || (m.provider.startsWith("openai") && code === 429);
            s.cool[`${m.provider}/${m.id}`] = now() + (long ? BLOCK_S : COOL_S);
          }
          save(s);
        }
        for (const ref of list) {
          if ((s.cool[ref] ?? 0) > now()) continue;
          const { provider, id: mid } = split(ref);
          if ((globalThis as any).__piKeysLeft?.(provider) === 0) continue; // provider hết key hôm nay
          const model = ctx.modelRegistry.find(provider, mid);
          if (!model) { dbg(`free/${id} bỏ ${ref}: không có trong danh mục`); continue; }
          if (!ctx.modelRegistry.hasConfiguredAuth?.(model)) { dbg(`free/${id} bỏ ${ref}: chưa có đăng nhập/key`); continue; }
          if (process.env.FREE_AUTO_DEBUG) process.stderr.write(`free/${id} -> ${ref}\n`);
          return route(model, level);
        }
        throw new Error(`free/${id}: mọi model đang nghỉ hoặc chưa đăng nhập; thử lại sau ít phút`);
      },
    });
  }
}

const DEV = [
  // Minh 25/11/2026: Codex lo cả Lead, Review và Dev chính; dev phụ là model miễn phí OpenRouter + ScaleRouter.
  // Không dùng DeepSeek trả phí nữa.
  `openai-${process.env.PI_DEV_ACCOUNT ?? "business3"}/gpt-6.2-sol`,
  "scalerouter/deepseek-v4.1-flash-free",          // sr-models tự xoay tiếp beam, mimo, hy4… trong ScaleRouter
  "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
  "openrouter/nvidia/nemotron-3.5-super-vl:free",
];

// Codex qua gói ChatGPT. Pi 1.6.0: đăng nhập provider "openai" bằng tài khoản ChatGPT (mỗi profile một lần:
// `bin\pi-role.cmd <vai> auth login openai`). Gói ChatGPT chỉ cho các model gpt-5.6-* và gpt-6.x
// (gpt-5.3-codex, gpt-5.5, gpt-5.4-nano, gpt-6.2-terra bị từ chối, thử 23/11).
// Minh 25/11: 6 tài khoản ChatGPT (gói pi-codex-accounts: provider openai-<nhãn>). Mỗi vai một tài khoản
// cố định, không tự xoay sang tài khoản khác khi hết lượt; hết lượt thì rơi xuống model miễn phí như cũ.
const LEAD_ACCOUNT = process.env.PI_LEAD_ACCOUNT ?? "business1";
const REVIEW_ACCOUNT = process.env.PI_REVIEW_ACCOUNT ?? "business2";
const LEAD = [
  // Minh 23/11/2026: Codex chỉ dùng một chế độ: gpt-6.2-sol, thinking medium.
  `openai-${LEAD_ACCOUNT}/gpt-6.2-sol`,
  // hết Codex: model miễn phí đạt 6/6 bài luật khó ngày 22/11
  "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
  "scalerouter/beam-free",
  "dahl/deepseek-ai/DeepSeek-V4-Flash-0731",
];
const REVIEW = [
  `openai-${REVIEW_ACCOUNT}/gpt-6.2-sol`,
  // hết Codex: thứ tự khác Lead để reviewer ít khi trùng model
  "scalerouter/beam-free",
  "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
  "dahl/MiniMaxAI/MiniMax-M2.7",
];
