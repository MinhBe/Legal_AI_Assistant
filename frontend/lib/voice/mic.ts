/* Micro -> PCM int16 16 kHz mono -> WebSocket /api/stt/live (voice intake).

Âm thanh chỉ đi tới máy chủ của Legal Agentic, không dùng Web Speech API của trình duyệt (cách đó gửi
âm thanh tới Google). Token đăng nhập đi qua ?token= vì WebSocket không gắn được header.
*/
import { API_BASE, getToken } from "@/lib/api";

export type SttEvent = { type: "partial" | "final" | "done" | "error" | "loading" | "ready"; text?: string; start?: number; end?: number };

const WORKLET = `
class Pcm16 extends AudioWorkletProcessor {
  constructor() { super(); this.ratio = sampleRate / 16000; this.acc = 0; this.out = []; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += 1;
      if (this.acc >= this.ratio) { this.acc -= this.ratio;
        const s = Math.max(-1, Math.min(1, ch[i])); this.out.push(s < 0 ? s * 0x8000 : s * 0x7fff); }
    }
    if (this.out.length >= 1600) { this.port.postMessage(Int16Array.from(this.out).buffer); this.out = []; }
    return true;
  }
}
registerProcessor("pcm16", Pcm16);`;

function wsUrl(): string {
  const base = API_BASE || window.location.origin;
  const u = new URL("/api/stt/live", base);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  const t = getToken();
  if (t) u.searchParams.set("token", t);
  return u.toString();
}

export class LiveMic {
  private ctx?: AudioContext;
  private stream?: MediaStream;
  private ws?: WebSocket;
  private node?: AudioWorkletNode;
  private chunks: Blob[] = [];
  private rec?: MediaRecorder;

  constructor(private onEvent: (e: SttEvent) => void) {}

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    this.ws = new WebSocket(wsUrl());
    this.ws.binaryType = "arraybuffer";
    this.ws.onmessage = (m) => { try { this.onEvent(JSON.parse(m.data)); } catch { /* bỏ tin hỏng */ } };
    this.ws.onerror = () => this.onEvent({ type: "error", text: "Mất kết nối chép lời" });
    await new Promise<void>((ok, fail) => { this.ws!.onopen = () => ok(); setTimeout(() => fail(new Error("timeout")), 8000); });
    this.ctx = new AudioContext();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await this.ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "pcm16");
    this.node.port.onmessage = (m) => { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(m.data); };
    src.connect(this.node);
    // giữ bản ghi gốc trong trình duyệt để khách nghe lại / đính kèm nếu muốn
    this.chunks = [];
    if (typeof MediaRecorder !== "undefined") {
      this.rec = new MediaRecorder(this.stream);
      this.rec.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
      this.rec.start(1000);
    }
  }

  /** Dừng micro, chốt câu cuối; trả bản ghi (webm) nằm trong trình duyệt. */
  async stop(): Promise<Blob | null> {
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close().catch(() => undefined);
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send("stop");
    const done = new Promise<Blob | null>((ok) => {
      if (!this.rec) return ok(null);
      this.rec.onstop = () => ok(this.chunks.length ? new Blob(this.chunks, { type: this.rec!.mimeType }) : null);
      this.rec.stop();
    });
    return done;
  }

  close() {
    try { this.ws?.close(); } catch { /* đã đóng */ }
  }
}
