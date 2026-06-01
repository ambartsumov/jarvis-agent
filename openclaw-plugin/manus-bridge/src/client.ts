/**
 * OpenManus WebSocket IPC client — async, no CLI per turn.
 * Protocol mirrors OpenManus-main/bridge/protocol.py
 */

import { randomUUID } from "node:crypto";
import WebSocket from "ws";

export type ManusBridgeEvent =
  | { event: "step"; step: number; max_steps?: number }
  | { event: "status"; title: string; step?: number; max_steps?: number }
  | { event: "thought"; content: string }
  | { event: "tool_start"; name: string; args?: Record<string, unknown> }
  | { event: "tool_end"; name: string; output?: string }
  | { event: "final"; content: string }
  | { event: "error"; message: string };

export type ManusBridgeRunInput = {
  message: string;
  sessionId?: string;
  context?: Record<string, unknown>;
  timeoutMs?: number;
  onStarted?: (reqId: string) => void;
};

export type ManusBridgeRunResult = {
  answer: string;
  events: ManusBridgeEvent[];
  error?: string;
};

type WsMessage =
  | { type: "event"; id: string; event: string; [key: string]: unknown }
  | { type: "done"; id: string }
  | { type: "error"; id: string; message: string }
  | { type: "pong"; id?: string };

export class ManusBridgeClient {
  private ws: WebSocket | null = null;
  private connectPromise: Promise<void> | null = null;

  constructor(private readonly wsUrl: string) {}

  async connect(): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }
    if (this.connectPromise) {
      return this.connectPromise;
    }
    this.connectPromise = this.connectWithRetry();
    try {
      await this.connectPromise;
    } finally {
      this.connectPromise = null;
    }
  }

  private async connectWithRetry(maxAttempts = 8): Promise<void> {
    let lastError: Error | undefined;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        await this.openSocket();
        return;
      } catch (err) {
        lastError = err instanceof Error ? err : new Error(String(err));
        if (attempt < maxAttempts - 1) {
          await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
        }
      }
    }
    throw lastError ?? new Error("WebSocket connect failed");
  }

  private openSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.wsUrl);
      ws.once("open", () => {
        this.ws = ws;
        resolve();
      });
      ws.once("error", (err) => {
        reject(err);
      });
    });
  }

  cancelRun(reqId: string): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return;
    }
    ws.send(JSON.stringify({ type: "cancel", id: reqId }));
  }

  async close(): Promise<void> {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  async run(
    input: ManusBridgeRunInput,
    onEvent?: (ev: ManusBridgeEvent) => void,
  ): Promise<ManusBridgeRunResult> {
    await this.connect();
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return { answer: "", events: [], error: "WebSocket not connected" };
    }

    const id = randomUUID();
    input.onStarted?.(id);
    const events: ManusBridgeEvent[] = [];
    let answer = "";
    let error: string | undefined;
    const timeoutMs = input.timeoutMs ?? 600_000;

    const payload = {
      type: "run",
      id,
      session_id: input.sessionId ?? "default",
      message: input.message,
      context: input.context ?? {},
    };

    return await new Promise((resolve) => {
      const timer = setTimeout(() => {
        cleanup();
        ws.send(JSON.stringify({ type: "cancel", id }));
        resolve({ answer: "⏱ Manus bridge timeout", events, error: "timeout" });
      }, timeoutMs);

      const onMessage = (raw: WebSocket.RawData) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(String(raw)) as WsMessage;
        } catch {
          return;
        }
        if (msg.id && msg.id !== id && msg.type !== "pong") {
          return;
        }

        if (msg.type === "event") {
          const ev = normalizeEvent(msg);
          if (ev) {
            events.push(ev);
            onEvent?.(ev);
            if (ev.event === "final") {
              answer = ev.content;
            }
            if (ev.event === "error") {
              error = ev.message;
            }
          }
        } else if (msg.type === "error") {
          error = msg.message;
        } else if (msg.type === "done") {
          cleanup();
          resolve({ answer: answer || "Готово.", events, error });
        }
      };

      const onError = (err: Error) => {
        cleanup();
        resolve({ answer: "", events, error: err.message });
      };

      const cleanup = () => {
        clearTimeout(timer);
        ws.off("message", onMessage);
        ws.off("error", onError);
      };

      ws.on("message", onMessage);
      ws.on("error", onError);
      ws.send(JSON.stringify(payload));
    });
  }
}

function normalizeEvent(msg: WsMessage & { type: "event" }): ManusBridgeEvent | null {
  switch (msg.event) {
    case "step":
      return {
        event: "step",
        step: Number(msg.step ?? 0),
        max_steps: Number(msg.max_steps ?? 0) || undefined,
      };
    case "status":
      return {
        event: "status",
        title: String(msg.title ?? "Работаю…"),
        step: Number(msg.step ?? 0) || undefined,
        max_steps: Number(msg.max_steps ?? 0) || undefined,
      };
    case "thought":
      return { event: "thought", content: String(msg.content ?? "") };
    case "tool_start":
      return {
        event: "tool_start",
        name: String(msg.name ?? "tool"),
        args: (msg.args as Record<string, unknown>) ?? {},
      };
    case "tool_end":
      return {
        event: "tool_end",
        name: String(msg.name ?? "tool"),
        output: String(msg.output ?? ""),
      };
    case "final":
      return { event: "final", content: String(msg.content ?? "") };
    case "error":
      return { event: "error", message: String(msg.message ?? "error") };
    default:
      return null;
  }
}

let sharedClient: ManusBridgeClient | null = null;

export function getManusBridgeClient(wsUrl: string): ManusBridgeClient {
  if (!sharedClient || (sharedClient as unknown as { wsUrl?: string }).wsUrl !== wsUrl) {
    sharedClient = new ManusBridgeClient(wsUrl);
    (sharedClient as unknown as { wsUrl?: string }).wsUrl = wsUrl;
  }
  return sharedClient;
}
