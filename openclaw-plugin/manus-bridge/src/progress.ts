import { ProxyAgent, fetch as undiciFetch } from "undici";
import type { ManusBridgeEvent } from "./client.js";

export type TelegramProgressState = {
  chatId: string;
  messageId?: number;
  title: string;
  step: number;
  maxSteps: number;
  lastUpdateMs: number;
};

type ProgressConfig = {
  botToken?: string;
  proxyUrl?: string;
};

let _cfg: ProgressConfig = {};
let _fetchImpl: typeof fetch | null = null;
let _proxyAgent: ProxyAgent | null = null;

export function configureTelegramProgress(cfg: ProgressConfig): void {
  _cfg = { ..._cfg, ...cfg };
  _fetchImpl = null;
  _proxyAgent = null;
}

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function toolActivityTitle(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("calendar")) return "📅 Календарь";
  if (n.includes("email")) return "📧 Почта";
  if (n === "bash") return "💻 Терминал";
  if (n.includes("browser")) return "🌐 Браузер";
  if (n.includes("remember")) return "💾 Запись в память";
  if (n.includes("recall") || n.includes("memory")) return "🧠 Память";
  if (n.includes("telegram")) return "✉️ Telegram";
  if (n.includes("whatsapp")) return "💬 WhatsApp";
  if (n.includes("web_search")) return "🔍 Поиск в интернете";
  if (n.includes("desktop")) return "🖥️ Рабочий стол";
  if (n.includes("terminate")) return "✅ Завершение";
  if (n.includes("str_replace") || n.includes("editor")) return "📝 Редактор файлов";
  if (n.includes("python")) return "🐍 Python";
  return `🔧 ${name}`;
}

export function buildProgressMessage(state: TelegramProgressState): string {
  const step = Math.max(0, state.step);
  if (state.maxSteps > 0) {
    const max = state.maxSteps;
    const capped = Math.min(step, max);
    const pct = Math.min(100, Math.round((capped / max) * 100));
    const filled = Math.round(pct / 10);
    const bar = "▓".repeat(filled) + "░".repeat(10 - filled);
    return (
      `🔄 <b>${escapeHtml(state.title)}</b>\n\n` +
      `<code>${bar}</code> ${pct}%\n` +
      `<i>шаг ${capped}/${max}</i>`
    );
  }
  const filled = Math.min(10, Math.max(1, step));
  const bar = "▓".repeat(filled) + "░".repeat(10 - filled);
  return (
    `🔄 <b>${escapeHtml(state.title)}</b>\n\n` +
    `<code>${bar}</code>\n` +
    `<i>шаг ${step}</i>`
  );
}

function botToken(): string | undefined {
  return (
    _cfg.botToken?.trim() ||
    process.env.TELEGRAM_BOT_TOKEN?.trim() ||
    process.env.TG_BOT_TOKEN?.trim() ||
    undefined
  );
}

function proxyUrl(): string | undefined {
  return _cfg.proxyUrl?.trim() || undefined;
}

function telegramFetch(): typeof fetch {
  if (_fetchImpl) return _fetchImpl;
  const proxy = proxyUrl();
  if (proxy) {
    _proxyAgent = new ProxyAgent(proxy);
    _fetchImpl = ((input: RequestInfo | URL, init?: RequestInit) =>
      undiciFetch(input as string | URL, {
        ...(init as Record<string, unknown>),
        dispatcher: _proxyAgent!,
      }) as unknown as Promise<Response>) as typeof fetch;
    return _fetchImpl;
  }
  _fetchImpl = globalThis.fetch.bind(globalThis);
  return _fetchImpl;
}

async function tgApi(method: string, body: Record<string, unknown>): Promise<unknown> {
  const token = botToken();
  if (!token) return undefined;

  const url = `https://api.telegram.org/bot${token}/${method}`;
  const init = {
    method: "POST" as const,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };

  for (const useProxy of [true, false]) {
    try {
      const fetchImpl =
        useProxy && proxyUrl()?.trim() ? telegramFetch() : globalThis.fetch.bind(globalThis);
      const res = await fetchImpl(url, init);
      if (res.ok) return res.json();
    } catch {
      continue;
    }
  }
  return undefined;
}

export async function upsertTelegramProgress(
  state: TelegramProgressState,
  force = false,
): Promise<void> {
  if (!state.chatId || !/^\d+$/.test(state.chatId)) return;
  const now = Date.now();
  if (!force && now - state.lastUpdateMs < 1200) return;
  state.lastUpdateMs = now;
  const text = buildProgressMessage(state);
  if (state.messageId) {
    await tgApi("editMessageText", {
      chat_id: state.chatId,
      message_id: state.messageId,
      text,
      parse_mode: "HTML",
    });
    return;
  }
  const data = (await tgApi("sendMessage", {
    chat_id: state.chatId,
    text,
    parse_mode: "HTML",
  })) as { result?: { message_id?: number } } | undefined;
  state.messageId = data?.result?.message_id;
}

export async function clearTelegramProgress(state: TelegramProgressState): Promise<void> {
  if (!state.chatId || !state.messageId) return;
  await tgApi("deleteMessage", {
    chat_id: state.chatId,
    message_id: state.messageId,
  });
  state.messageId = undefined;
}

export async function sendTelegramMessage(
  chatId: string,
  text: string,
  extra?: { reply_markup?: { inline_keyboard: unknown[] } },
): Promise<void> {
  if (!chatId || !/^\d+$/.test(chatId) || !text.trim()) return;
  await tgApi("sendMessage", {
    chat_id: chatId,
    text,
    parse_mode: "HTML",
    ...extra,
  });
}

export function applyProgressEvent(state: TelegramProgressState, ev: ManusBridgeEvent): void {
  switch (ev.event) {
    case "status":
      if (ev.title) state.title = ev.title;
      if (ev.step) state.step = ev.step;
      if (ev.max_steps) state.maxSteps = ev.max_steps;
      break;
    case "step":
      state.step = ev.step;
      if (ev.max_steps) state.maxSteps = ev.max_steps;
      if (state.title === "Запуск агента") state.title = "🤔 Думаю…";
      break;
    case "tool_start":
      state.title = toolActivityTitle(ev.name);
      state.step = Math.max(state.step, 1);
      if (!state.maxSteps && state.step >= 3) {
        state.maxSteps = state.step + 2;
      } else if (state.maxSteps && state.step >= state.maxSteps) {
        state.maxSteps = state.step + 2;
      }
      break;
    default:
      break;
  }
}
