/** SSE 帧解析 —— 纯函数，**不抛异常**：一个坏帧不该毁掉整条流。
 *
 *  ★ 为什么单独抽出来：`/chat`（POST）与 `/sessions/{sid}/events`（GET）两条流的
 *    **帧语法完全相同**（`id:` / `event:` / `data:` + 空行分隔），只有语义不同。
 *    抽成一份，两条流共用；也便于用**真实抓取的流**做单测（`__fixtures__/gateway/*.sse`）。
 *
 *  ★ MVP 的经验：把「单帧解析」抽成纯函数，让**流式**与**全量**两条路径共用同一份代码 ——
 *    否则只有其中一条有护栏。本模块的 `drainFrames()` 正是那个共用点。
 *
 *  ⚠️ 两条流的语义差异（**不要混淆**）：
 *    - `/chat`：`event:` 名 = **对话事件 kind**（text/final/notice/error/tool_call/tool_error），
 *      `data:` 是 payload 本身，**没有 `id:`**。
 *    - `/events`：`event:` 名 = **通道**（evidence/telemetry），`id:` = 单调 `seq`，
 *      `data:` 是 `{seq, kind, payload, at}` 的包装。
 */

export interface SseFrame {
  /** `event:` 名 */
  event: string;
  /** `data:` 的**原始文本**（未做 JSON.parse —— 由上层按语义解析） */
  data: string;
  /** `id:` 的数值形式；无 `id:` 或非数值时为 `null` */
  id: number | null;
}

/** 解析单个帧块（不含分隔空行）。缺 `event` 或 `data` → `null`（坏帧跳过，不抛）。 */
export function parseFrameBlock(block: string): SseFrame | null {
  let event = "";
  let data = "";
  let id: number | null = null;

  for (const rawLine of block.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      // SSE 允许一个帧里多行 data，按换行拼接
      const chunk = line.slice("data:".length).trimStart();
      data = data ? `${data}\n${chunk}` : chunk;
    } else if (line.startsWith("id:")) {
      const n = Number(line.slice("id:".length).trim());
      id = Number.isFinite(n) ? n : null;
    }
  }

  if (!event || !data) return null;
  return { event, data, id };
}

/**
 * 从缓冲区切出所有**完整**帧，返回 `[帧数组, 剩余缓冲]`。
 *
 * ★ 流式与全量两条路径共用此函数：流式循环里反复 `push → drainFrames`；
 *   全量路径直接对整段文本调一次。**同一份代码** ⇒ 两条路径不会各自长歪。
 */
export function drainFrames(buf: string): { frames: SseFrame[]; rest: string } {
  const frames: SseFrame[] = [];
  let rest = buf;
  let idx: number;
  while ((idx = rest.indexOf("\n\n")) >= 0) {
    const block = rest.slice(0, idx);
    rest = rest.slice(idx + 2);
    const frame = parseFrameBlock(block);
    if (frame) frames.push(frame);
  }
  return { frames, rest };
}

/** 把一段**完整**响应体切成帧（全量路径 / 单测用）。 */
export function parseAllFrames(text: string): SseFrame[] {
  return drainFrames(text.replace(/\r\n/g, "\n")).frames;
}

/** 逐帧读取一个流式响应。`\r\n` 归一化后交给 `drainFrames`。 */
export async function* readSse(resp: Response): AsyncGenerator<SseFrame> {
  const body = resp.body;
  if (!body) return;
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      const { frames, rest } = drainFrames(buf);
      buf = rest;
      for (const f of frames) yield f;
    }
    // 收尾：有些实现最后一帧不带尾部空行
    buf += decoder.decode();
    const tail = parseFrameBlock(buf.replace(/\r\n/g, "\n"));
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}
