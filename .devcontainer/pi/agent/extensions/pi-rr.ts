/**
 * pi-rr: xoay vòng (round robin) API key cho từng request, ngay trong Pi.
 *
 * Gõ trong Pi:
 *   /pi-rr          bật xoay vòng + xem trạng thái
 *   /pi-rr off      tắt (quay về key trong biến môi trường)
 *   /pi-rr status   chỉ xem trạng thái
 *   /pi-rr reload   đọc lại file key sau khi sửa
 *
 * Key nằm ở <pi>\keys\<provider>.keys (mỗi dòng 1 key, # là chú thích), ví dụ dahl.keys, deepseek.keys.
 * Mỗi request gửi tới provider có file key sẽ lấy key kế tiếp; key nào vừa bị 429/5xx thì nghỉ COOL_S giây.
 * Bộ đếm (.rr-<p>) và file nghỉ (.cool-<p>-<n>) dùng chung với bin/pi-rr và bin/pi-cool,
 * nên nhiều cửa sổ Pi và worker chạy song song vẫn chia đều tải.
 * Trạng thái bật/tắt lưu ở keys/.rr-enabled, nên worker chạy `pi -p` cũng được xoay vòng.
 * Không bao giờ in giá trị key, chỉ in số thứ tự #i (đếm từ 0, như bin/pi-rr).
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const COOL_S = Number(process.env.PI_RR_COOL_S ?? 90);
const AGENT_DIR = process.env.PI_CODING_AGENT_DIR ?? path.join(os.homedir(), ".pi", "agent");
// pi-dev: keys nằm ở <pi-dev>/keys. Agent dir có thể là <pi-dev>/agent hoặc <pi-dev>/profiles/<tên>.
const KEYS_DIR =
  process.env.PI_KEYS_DIR ??
  [path.resolve(AGENT_DIR, "..", "keys"), path.resolve(AGENT_DIR, "..", "..", "keys")].find((d) => fs.existsSync(d)) ??
  path.resolve(AGENT_DIR, "..", "keys");
const ENV_VAR: Record<string, string> = { dahl: "DAHL_API_KEY", deepseek: "DEEPSEEK_API_KEY", scalerouter: "SCALEROUTER_API_KEY", codex: "OPENAI_API_KEY", openrouter: "OPENROUTER_API_KEY" };

const keyCache = new Map<string, string[]>();
const keyNames = new Map<string, string[]>();
const label = (p: string, n: number) => `#${n}${keyNames.get(p)?.[n] ? ` (${keyNames.get(p)![n]})` : ""}`;
const uses = new Map<string, number[]>();
let last: { provider: string; n: number } | undefined;

const file = (name: string) => path.join(KEYS_DIR, name);
const now = () => Math.floor(Date.now() / 1000);

function loadKeys(provider: string, fresh = false): string[] {
  if (!fresh && keyCache.has(provider)) return keyCache.get(provider)!;
  let keys: string[] = [];
  try {
    const lines = fs
      .readFileSync(file(`${provider}.keys`), "utf8")
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith("#"))
      // Ô trống dạng "tên =" (chưa dán key) thì bỏ qua.
      .filter((l) => !/^[\w.-]+\s*=\s*$/.test(l));
    // Cho phép dạng "tên = key" (vd. openrouter-165 = sk-...): key là phần sau "=", tên dùng khi báo lỗi.
    keyNames.set(provider, lines.map((l) => l.match(/^([\w.-]+)\s*=/)?.[1] ?? ""));
    keys = lines.map((l) => l.match(/^[\w.-]+\s*=\s*([^=\s]\S*)$/)?.[1] ?? l);
  } catch {
    /* chưa có file key cho provider này */
  }
  keyCache.set(provider, keys);
  return keys;
}

function providers(): string[] {
  try {
    return fs
      .readdirSync(KEYS_DIR)
      .filter((f) => f.endsWith(".keys"))
      .map((f) => f.slice(0, -5));
  } catch {
    return [];
  }
}

const isEnabled = () => fs.existsSync(file(".rr-enabled"));

function setEnabled(on: boolean) {
  if (on) fs.writeFileSync(file(".rr-enabled"), String(now()));
  else fs.rmSync(file(".rr-enabled"), { force: true });
}

function coolingLeft(provider: string, n: number): number {
  try {
    const t = Number(fs.readFileSync(file(`.cool-${provider}-${n}`), "utf8").trim());
    return Math.max(0, t + COOL_S - now());
  } catch {
    return 0;
  }
}

/** Khoá liên tiến trình giống bin/pi-rr (mkdir là thao tác nguyên tử). */
function withLock<T>(provider: string, fn: () => T): T {
  const lock = file(`.lock-${provider}`);
  let got = false;
  for (let i = 0; i < 50 && !got; i++) {
    try {
      fs.mkdirSync(lock);
      got = true;
    } catch {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
    }
  }
  try {
    return fn();
  } finally {
    if (got) fs.rmSync(lock, { recursive: true, force: true });
  }
}

/**
 * Lấy key kế tiếp (bỏ qua key đang nghỉ). Quy ước giống hệt bin/pi-rr và bin/pi-cool:
 * số thứ tự đếm từ 0, .rr-<p> lưu số của key vừa dùng, .cool-<p>-<i> đánh dấu key i đang nghỉ.
 */
// Hạn mức tự đặt mỗi key mỗi ngày (UTC), Minh 22/11/2026: OpenRouter 30 lượt/tài khoản/ngày.
// Đổi bằng file keys/limits.json, ví dụ {"openrouter": 30, "scalerouter": 0} (0 = không giới hạn).
const DEFAULT_CAPS: Record<string, number> = { openrouter: 30 };
function dailyCap(provider: string): number {
  try {
    const j = JSON.parse(fs.readFileSync(file("limits.json"), "utf8"));
    if (typeof j[provider] === "number") return j[provider];
  } catch {
    /* không có file: dùng mặc định */
  }
  return DEFAULT_CAPS[provider] ?? 0;
}
const today = () => new Date().toISOString().slice(0, 10);
function readDaily(provider: string): { date: string; counts: Record<number, number> } {
  try {
    const j = JSON.parse(fs.readFileSync(file(`.daily-${provider}.json`), "utf8"));
    if (j.date === today()) return { date: j.date, counts: j.counts ?? {} };
  } catch {
    /* ngày mới hoặc chưa có */
  }
  return { date: today(), counts: {} };
}
function writeDaily(provider: string, d: { date: string; counts: Record<number, number> }) {
  try {
    fs.writeFileSync(file(`.daily-${provider}.json`), JSON.stringify(d));
  } catch {
    /* bỏ qua */
  }
}
/** Số key còn dùng được hôm nay (chưa chạm hạn mức ngày, không nghỉ). free-auto dùng để bỏ qua provider hết key. */
function keysLeft(provider: string): number {
  const keys = loadKeys(provider);
  if (keys.length === 0) return Infinity; // provider không dùng file key (vd. đăng nhập ChatGPT): pi-rr không quản
  const cap = dailyCap(provider);
  const d = readDaily(provider);
  return keys.filter((_, i) => (!cap || (d.counts[i] ?? 0) < cap) && coolingLeft(provider, i) === 0).length;
}
(globalThis as any).__piKeysLeft = keysLeft;

function pick(provider: string): { key: string; n: number } | undefined {
  const keys = loadKeys(provider);
  if (keys.length === 0) return undefined;
  const counter = file(`.rr-${provider}`);
  return withLock(provider, () => {
    let lastUsed = -1;
    try {
      const v = Number(fs.readFileSync(counter, "utf8").trim());
      if (Number.isInteger(v)) lastUsed = v;
    } catch {
      /* lần đầu */
    }
    const cap = dailyCap(provider);
    const d = readDaily(provider);
    let chosen = -1;
    let fallback = 0;
    for (let step = 1; step <= keys.length; step++) {
      const i = (((lastUsed + step) % keys.length) + keys.length) % keys.length;
      if (cap && (d.counts[i] ?? 0) >= cap) continue; // hết hạn mức tự đặt trong ngày
      fallback = i;
      if (coolingLeft(provider, i) === 0) {
        chosen = i;
        break;
      }
    }
    if (chosen < 0) {
      // mọi key đang nghỉ: provider có hạn mức ngày mà hết sạch thì không gửi nữa; không thì dùng tạm key nghỉ
      if (cap && keys.every((_, i) => (d.counts[i] ?? 0) >= cap)) return undefined;
      chosen = fallback;
    }
    if (cap) {
      d.counts[chosen] = (d.counts[chosen] ?? 0) + 1;
      writeDaily(provider, d);
    }
    try {
      fs.writeFileSync(counter, String(chosen));
    } catch {
      /* không ghi được thì vẫn chạy */
    }
    const u = uses.get(provider) ?? [];
    u[chosen] = (u[chosen] ?? 0) + 1;
    uses.set(provider, u);
    return { key: keys[chosen], n: chosen };
  });
}

function statusText(): string {
  const lines = [`pi-rr: ${isEnabled() ? "BẬT" : "TẮT"} · thư mục key: ${KEYS_DIR}`];
  const ps = providers();
  if (ps.length === 0) lines.push("  chưa có file *.keys");
  for (const p of ps) {
    const keys = loadKeys(p);
    const u = uses.get(p) ?? [];
    const parts = keys.map((_, i) => {
      const cool = coolingLeft(p, i);
      const cap = dailyCap(p);
      const used = readDaily(p).counts[i] ?? 0;
      return `${label(p, i)}:${u[i] ?? 0} lần${cap ? ` (hôm nay ${used}/${cap})` : ""}${cool ? ` (nghỉ ${cool}s)` : ""}`;
    });
    lines.push(`  ${p}: ${keys.length} key · ${parts.join(" · ") || "trống"}`);
  }
  return lines.join("\n");
}

function cool(provider: string, n: number, why: string, ctx: { hasUI: boolean; ui: { notify(m: string, t: "info" | "warning" | "error"): void } }) {
  try {
    fs.writeFileSync(file(`.cool-${provider}-${n}`), String(now()));
  } catch {
    /* bỏ qua */
  }
  const msg = `pi-rr: ${provider} key ${label(provider, n)} ${why}, cho nghỉ ${COOL_S}s`;
  if (ctx.hasUI) ctx.ui.notify(msg, "warning");
  else process.stderr.write(msg + "\n");
}

export default function (pi: ExtensionAPI) {
  // Để Pi coi provider là "đã cấu hình" ($DAHL_API_KEY trong models.json) dù chưa set biến môi trường.
  for (const p of providers()) {
    const envName = ENV_VAR[p];
    const keys = loadKeys(p);
    if (envName && !process.env[envName] && keys.length) process.env[envName] = keys[0];
  }

  pi.on("before_provider_headers", (event, ctx) => {
    // Request trước bị lỗi (429/5xx/mạng) thì SDK ném lỗi, after_provider_response không chạy:
    // key đó chưa được xác nhận, cho nghỉ rồi mới chọn key mới.
    if (last) cool(last.provider, last.n, "lỗi", ctx);
    last = undefined;
    // model ảo (free/dev, free/auto): lấy provider thật mà router vừa chọn
    const sel = ctx.model?.provider;
    const phys = (globalThis as any).__piPhysicalProvider;
    const provider = sel && loadKeys(sel).length ? sel : phys ?? sel;
    if (!provider || !isEnabled()) return;
    const got = pick(provider);
    if (!got) return;
    for (const k of Object.keys(event.headers)) {
      if (k.toLowerCase() === "authorization") delete event.headers[k];
    }
    event.headers["Authorization"] = `Bearer ${got.key}`;
    last = { provider, n: got.n };
    if (process.env.PI_RR_DEBUG) process.stderr.write(`pi-rr: ${provider}=#${got.n}\n`);
  });

  // Key hết lượt trong ngày (OpenRouter "free-models-per-day"): nghỉ tới 0h UTC hôm sau, không chỉ COOL_S
  // giây, để các key còn lượt gánh tiếp. Lỗi HTTP làm SDK ném lỗi, nên đọc từ errorMessage của tin nhắn.
  pi.on("message_end", (event, ctx) => {
    const m = (event as any).message;
    if (!last || m?.role !== "assistant" || m?.stopReason !== "error") return;
    if (!/per-day|per day|daily/i.test(String(m.errorMessage ?? ""))) return;
    const midnight = Math.ceil(Date.now() / 86_400_000) * 86_400;
    try {
      fs.writeFileSync(file(`.cool-${last.provider}-${last.n}`), String(midnight - COOL_S));
    } catch {
      /* bỏ qua */
    }
    const msg = `pi-rr: ${last.provider} key ${label(last.provider, last.n)} hết lượt hôm nay, nghỉ tới 0h UTC`;
    if (ctx.hasUI) ctx.ui.notify(msg, "warning");
    else process.stderr.write(msg + "\n");
    last = undefined;
  });

  pi.on("after_provider_response", (event, ctx) => {
    if (!last) return;
    if (event.status === 429 || event.status >= 500) cool(last.provider, last.n, String(event.status), ctx);
    last = undefined; // đã có phản hồi: key này ổn
  });

  pi.on("session_start", (_event, ctx) => {
    if (ctx.hasUI && isEnabled()) ctx.ui.setStatus("pi-rr", "rr: bật");
  });

  pi.registerCommand("pi-rr", {
    description: "Xoay vòng API key theo từng request (on | off | status | reload)",
    getArgumentCompletions: (prefix: string) => {
      const items = ["on", "off", "status", "reload"]
        .filter((v) => v.startsWith(prefix))
        .map((v) => ({ value: v, label: v }));
      return items.length ? items : null;
    },
    handler: async (args, ctx) => {
      const a = (args ?? "").trim().toLowerCase();
      try {
        if (a === "" || a === "on") setEnabled(true);
        else if (a === "off") setEnabled(false);
        else if (a === "reload") for (const p of providers()) loadKeys(p, true);
        else if (a !== "status") {
          ctx.ui.notify("Dùng: /pi-rr [on|off|status|reload]", "warning");
          return;
        }
      } catch (e) {
        ctx.ui.notify(`pi-rr: không ghi được vào ${KEYS_DIR}: ${String(e)}`, "error");
        return;
      }
      ctx.ui.setStatus("pi-rr", isEnabled() ? "rr: bật" : undefined);
      ctx.ui.notify(statusText(), "info");
    },
  });
}
