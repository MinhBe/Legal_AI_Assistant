/**
 * sr-models: xoay model trong provider ScaleRouter (Minh 22/11/2026).
 *
 * ScaleRouter có nhiều model miễn phí, mỗi model giới hạn riêng. Với mỗi request tới provider
 * "scalerouter", extension thay trường `model` trong payload bằng model đầu tiên còn dùng được theo
 * thứ tự ưu tiên (deepseek-v4.1-flash-free trước). Model vừa lỗi thì nghỉ:
 *   429 / 5xx / lỗi mạng: nghỉ COOL_S giây (mặc định 120)
 *   401 / 402 / 403:      nghỉ BLOCK_S giây (mặc định 3600: hết tiền, chưa được phép dùng)
 * Request sau tự sang model kế tiếp; Pi tự thử lại khi gặp 429/5xx nên lần thử lại dùng model mới.
 *
 * Thứ tự model: file <pi-dev>/keys/scalerouter.models (mỗi dòng một id, # là chú thích) nếu có,
 * không thì danh sách ORDER dưới đây. Trạng thái nghỉ lưu ở keys/.srm-cool.json, dùng chung cho
 * mọi cửa sổ Pi.
 *
 * Gõ trong Pi: /sr-models (xem trạng thái) · /sr-models reset (xoá trạng thái nghỉ)
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const PROVIDER = "scalerouter";
const COOL_S = Number(process.env.SRM_COOL_S ?? 120);
const BLOCK_S = Number(process.env.SRM_BLOCK_S ?? 3600);
// glm-5.3-flash không có ở đây: stream trả content dạng mảng {type:"thinking"} không chuẩn OpenAI,
// và qua Pi bị 502. Trả phí, nên cũng không nên tự rơi vào.
const ORDER = [
  // Thứ tự theo thử nghiệm 22/11/2026 (key mới): DeepSeek trước theo ý Minh; beam-free đạt 6/6 câu luật khó.
  "deepseek-v4.1-flash-free",
  "beam-free",
  "mimo-v2.6-flash-free",
  "hy4-flash-free",
  "nemotron-3.5-super-vl-free",
  "tidepool-alpha-free",
  "iceman-free",
  "flint-40b-free",
  "longcat-2.5-free",
  "nemotron-3.5-lightning-free",
  // big-pickle: key này bị 401 "not allowed"; glm-5.3-flash: trả phí, định dạng stream lạ.
];

const AGENT_DIR = process.env.PI_CODING_AGENT_DIR ?? path.join(os.homedir(), ".pi", "agent");
const KEYS_DIR =
  process.env.PI_KEYS_DIR ??
  [path.resolve(AGENT_DIR, "..", "keys"), path.resolve(AGENT_DIR, "..", "..", "keys")].find((d) => fs.existsSync(d)) ??
  path.resolve(AGENT_DIR, "..", "keys");
const COOL_FILE = path.join(KEYS_DIR, ".srm-cool.json");
const now = () => Math.floor(Date.now() / 1000);

function order(): string[] {
  try {
    const lines = fs
      .readFileSync(path.join(KEYS_DIR, "scalerouter.models"), "utf8")
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith("#"));
    if (lines.length) return lines;
  } catch {
    /* không có file: dùng ORDER */
  }
  return ORDER;
}

function readCool(): Record<string, number> {
  try {
    return JSON.parse(fs.readFileSync(COOL_FILE, "utf8"));
  } catch {
    return {};
  }
}

function coolModel(model: string, seconds: number) {
  const c = readCool();
  c[model] = now() + seconds;
  try {
    fs.writeFileSync(COOL_FILE, JSON.stringify(c));
  } catch {
    /* không ghi được thì vẫn chạy */
  }
}

function pickModel(): string {
  const c = readCool();
  const list = order();
  const free = list.find((m) => (c[m] ?? 0) <= now());
  if (free) return free;
  // tất cả đang nghỉ: lấy model hết nghỉ sớm nhất
  return [...list].sort((a, b) => (c[a] ?? 0) - (c[b] ?? 0))[0];
}

function say(ctx: any, msg: string) {
  if (ctx.hasUI) ctx.ui.notify(msg, "warning");
  else process.stderr.write(msg + "\n");
}

// model ảo: provider thật do free-auto ghi vào globalThis
const provOf = (ctx: any) =>
  ctx.model?.provider === PROVIDER ? PROVIDER : ((globalThis as any).__piPhysicalProvider ?? ctx.model?.provider);

export default function (pi: ExtensionAPI) {
  let pending: string | undefined; // model của request đang chờ phản hồi

  pi.on("before_provider_request", (event, ctx) => {
    if (provOf(ctx) !== PROVIDER) return;
    // request trước ném lỗi trước khi có phản hồi (mạng, hết giờ): cho model đó nghỉ ngắn
    if (pending) {
      coolModel(pending, COOL_S);
      say(ctx, `sr-models: ${pending} lỗi mạng, nghỉ ${COOL_S}s`);
    }
    // chỉ ô "tự xoay" (model đầu danh sách) mới bị thay; model chọn đích danh (vd. beam-free cho lead) giữ nguyên
    const asked = (event.payload as any)?.model;
    if (asked && asked !== order()[0]) { pending = asked; return; }
    const model = pickModel();
    pending = model;
    if (ctx.hasUI) ctx.ui.setStatus?.("sr-models", `sr: ${model}`);
    const payload = event.payload as Record<string, unknown> | undefined;
    if (!payload || typeof payload !== "object") return;
    return { ...payload, model };
  });

  pi.on("after_provider_response", (event, ctx) => {
    if (provOf(ctx) !== PROVIDER || !pending) return;
    const model = pending;
    pending = undefined;
    if ([401, 402, 403].includes(event.status)) {
      coolModel(model, BLOCK_S);
      say(ctx, `sr-models: ${model} bị từ chối (${event.status}), bỏ qua ${BLOCK_S}s`);
    } else if (event.status === 429 || event.status >= 500) {
      coolModel(model, COOL_S);
      say(ctx, `sr-models: ${model} quá tải (${event.status}), nghỉ ${COOL_S}s`);
    }
  });

  // Lỗi HTTP (vd. 403) làm SDK ném lỗi nên after_provider_response không chạy; Pi kết thúc tin nhắn
  // với stopReason "error" và errorMessage bắt đầu bằng mã lỗi (vd. '403 "Business Error"').
  pi.on("message_end", (event, ctx) => {
    const m = (event as any).message;
    if (!pending || m?.role !== "assistant" || m?.stopReason !== "error") return;
    if (provOf(ctx) !== PROVIDER) return;
    const model = pending;
    pending = undefined;
    const code = Number(String(m.errorMessage ?? "").match(/^(\d{3})\b/)?.[1] ?? 0);
    const secs = [401, 402, 403].includes(code) ? BLOCK_S : COOL_S;
    coolModel(model, secs);
    say(ctx, `sr-models: ${model} lỗi ${code || "?"}, nghỉ ${secs}s; lần sau dùng ${pickModel()}`);
  });

  pi.registerCommand("sr-models", {
    description: "Xoay model ScaleRouter: xem trạng thái | reset",
    handler: async (args, ctx) => {
      if ((args ?? "").trim() === "reset") fs.rmSync(COOL_FILE, { force: true });
      const c = readCool();
      const lines = order().map((m) => {
        const left = (c[m] ?? 0) - now();
        return `  ${m}${left > 0 ? ` (nghỉ ${left}s)` : ""}`;
      });
      const msg = `sr-models: đang dùng ${pickModel()}\n${lines.join("\n")}`;
      if (ctx.hasUI) ctx.ui.notify(msg, "info");
      else process.stdout.write(msg + "\n");
    },
  });
}
