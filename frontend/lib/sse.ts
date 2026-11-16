// Đọc SSE từ một POST request bằng fetch + ReadableStream.
// Mỗi sự kiện: dòng "event: <type>" và "data: <json>", ngăn nhau bằng dòng trống.

import { apiFetch } from "@/lib/api";

export type SSEHandler = (event: string, data: any) => void;

export async function streamChat(
  apiBase: string,
  body: Record<string, unknown>,
  onEvent: SSEHandler,
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetch(`${apiBase}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    // 429/401: máy chủ trả {"detail": ...} — chuyển nguyên văn để chat hiện đúng lý do
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch { /* không phải JSON */ }
    throw new Error(detail || `Chat request failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);

      let event = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length) {
        const raw = dataLines.join("\n");
        try {
          onEvent(event, JSON.parse(raw));
        } catch {
          onEvent(event, raw);
        }
      }
    }
  }
}
