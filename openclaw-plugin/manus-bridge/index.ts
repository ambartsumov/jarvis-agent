import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { getManusBridgeClient, type ManusBridgeEvent } from "./src/client.js";
import {
  applyProgressEvent,
  clearTelegramProgress,
  configureTelegramProgress,
  escapeHtml,
  sendTelegramMessage,
  type TelegramProgressState,
  upsertTelegramProgress,
} from "./src/progress.js";
import {
  buildQueueChoiceInteractive,
  clearActiveManusRun,
  decodeQueueSessionId,
  enqueueFollowup,
  getActiveManusRun,
  isManusSessionActive,
  setActiveManusRun,
  setConflictPending,
  shiftFollowup,
  takeConflictPending,
  type PendingManusRun,
} from "./src/session-queue.js";

type PluginConfig = {
  wsUrl?: string;
  enabled?: boolean;
  interceptAgent?: boolean;
  skipHeartbeat?: boolean;
  telegramProgress?: boolean;
  botToken?: string;
  proxyUrl?: string;
};

type ManusHookCtx = {
  channelId?: string;
  sessionKey?: string;
  sessionId?: string;
  agentId?: string;
  runId?: string;
  workspaceDir?: string;
};

function isInternalAnswer(text: string): boolean {
  const t = text.trim();
  if (!t) return true;
  if (/^(Let me|I'll |I will |Checking |Searching |Looking )/i.test(t)) return true;
  const cyrillic = (t.match(/[\u0400-\u04FF]/g) ?? []).length;
  return t.length > 25 && cyrillic < Math.max(4, t.length * 0.06);
}

function resolveSessionId(ctx: ManusHookCtx): string {
  return ctx.sessionKey ?? ctx.sessionId ?? "default";
}

function buildPending(message: string, ctx: ManusHookCtx): PendingManusRun {
  const sessionId = resolveSessionId(ctx);
  return {
    message,
    sessionId,
    context: {
      channel: ctx.channelId,
      user_id:
        ctx.channelId && /^\d+$/.test(String(ctx.channelId)) ? Number(ctx.channelId) : undefined,
      agentId: ctx.agentId,
      runId: ctx.runId,
      workspaceDir: ctx.workspaceDir,
    },
  };
}

async function executeManusRun(params: {
  wsUrl: string;
  pending: PendingManusRun;
  telegramProgress: boolean;
  chatId: string;
  logger: { info: (msg: string) => void; error: (msg: string) => void };
  asyncStart?: boolean;
}): Promise<{ handled: true; reply: { text: string }; reason: string }> {
  const { wsUrl, pending, telegramProgress, chatId, logger, asyncStart = true } = params;

  const runOnce = async (job: PendingManusRun): Promise<string> => {
    const client = getManusBridgeClient(wsUrl);
    const showProgress = telegramProgress && /^\d+$/.test(chatId);
    const progressState: TelegramProgressState = {
      chatId,
      title: "Запуск агента",
      step: 0,
      maxSteps: 0,
      lastUpdateMs: 0,
    };

    let reqId = "";
    setActiveManusRun(job.sessionId, {
      ...job,
      reqId: "pending",
      cancel: () => {
        if (reqId) client.cancelRun(reqId);
      },
    });

    try {
      if (showProgress) {
        try {
          await upsertTelegramProgress(progressState, true);
        } catch {
          /* best-effort */
        }
      }

      const result = await client.run(
        {
          message: job.message,
          sessionId: job.sessionId,
          context: job.context,
          timeoutMs: 600_000,
          onStarted: (startedId) => {
            reqId = startedId;
            setActiveManusRun(job.sessionId, {
              ...job,
              reqId: startedId,
              cancel: () => client.cancelRun(startedId),
            });
          },
        },
        async (ev: ManusBridgeEvent) => {
          if (!showProgress) return;
          applyProgressEvent(progressState, ev);
          try {
            await upsertTelegramProgress(progressState);
          } catch {
            /* ignore */
          }
        },
      );

      if (showProgress) {
        try {
          await clearTelegramProgress(progressState);
        } catch {
          /* ignore */
        }
      }

      let answer = (result.answer || "").trim();
      if (isInternalAnswer(answer)) {
        const finalEv = [...result.events].reverse().find((e) => e.event === "final");
        if (finalEv && finalEv.event === "final" && !isInternalAnswer(finalEv.content)) {
          answer = finalEv.content.trim();
        }
      }
      if (isInternalAnswer(answer)) {
        answer = "Задача выполнена. Если нужны детали — уточни, что именно проверить.";
      }
      if (result.error && !answer) {
        return `❌ Manus: ${result.error}`;
      }
      return answer || "Готово.";
    } catch (err) {
      logger.error(`manus-bridge run failed: ${String(err)}`);
      return `❌ Manus bridge: ${String(err)}`;
    } finally {
      clearActiveManusRun(job.sessionId);
    }
  };

  const deliverChain = async (job: PendingManusRun): Promise<void> => {
    const text = await runOnce(job);
    if (/^\d+$/.test(chatId)) {
      await sendTelegramMessage(chatId, text);
    }
    const next = shiftFollowup(job.sessionId);
    if (next) {
      logger.info(`manus-bridge: draining followup session=${job.sessionId}`);
      await deliverChain(next);
    }
  };

  if (asyncStart) {
    void deliverChain(pending).catch((err) => {
      logger.error(`manus-bridge async run failed: ${String(err)}`);
      if (/^\d+$/.test(chatId)) {
        void sendTelegramMessage(chatId, `❌ Ошибка: ${String(err)}`);
      }
    });
    return {
      handled: true,
      reply: { text: "🔄 Принял, работаю…" },
      reason: "manus-bridge-async",
    };
  }

  const answer = await runOnce(pending);
  return { handled: true, reply: { text: answer }, reason: "manus-bridge" };
}

function queueKeyboardMarkup(sessionId: string) {
  const interactive = buildQueueChoiceInteractive(sessionId);
  const block = interactive.blocks[0];
  if (!block || block.type !== "buttons") return undefined;
  return {
    inline_keyboard: [
      block.buttons.map((btn) => ({
        text: btn.label,
        callback_data: btn.value.slice(0, 64),
      })),
    ],
  };
}

export default definePluginEntry({
  id: "manus-bridge",
  name: "OpenManus Bridge",
  description:
    "WebSocket IPC to OpenManus Python agent — OpenClaw handles Telegram/sessions, Manus runs Think-Act-Observe.",
  register(api) {
    const cfg = (api.pluginConfig ?? {}) as PluginConfig;
    const wsUrl = cfg.wsUrl ?? process.env.MANUS_BRIDGE_WS ?? "ws://127.0.0.1:8765/manus";
    const enabled = cfg.enabled !== false;
    const intercept = cfg.interceptAgent !== false;
    const skipHeartbeat = cfg.skipHeartbeat !== false;
    const telegramProgress = cfg.telegramProgress !== false;
    const tgCfg = api.config?.channels?.telegram;
    const tgProxy =
      typeof tgCfg === "object" && tgCfg && "proxy" in tgCfg
        ? String((tgCfg as { proxy?: string }).proxy ?? "")
        : "";
    const botToken =
      cfg.botToken ??
      ((typeof tgCfg === "object" && tgCfg && "botToken" in tgCfg
        ? String((tgCfg as { botToken?: string }).botToken ?? "")
        : "") ||
        undefined);
    configureTelegramProgress({
      botToken,
      proxyUrl: cfg.proxyUrl || tgProxy || undefined,
    });

    api.registerService({
      id: "manus-bridge",
      async start(ctx) {
        if (!enabled) {
          ctx.logger.info("manus-bridge disabled in config");
          return;
        }
        try {
          const client = getManusBridgeClient(wsUrl);
          await client.connect();
          ctx.logger.info(`manus-bridge connected: ${wsUrl}`);
        } catch (err) {
          ctx.logger.warn(`manus-bridge connect failed (will retry on run): ${String(err)}`);
        }
      },
      async stop() {
        const client = getManusBridgeClient(wsUrl);
        await client.close();
      },
    });

    api.registerInteractiveHandler({
      channel: "telegram",
      namespace: "manus",
      handler: async (ctx) => {
        const match = ctx.callback.payload.match(/^queue:(cancel|followup|priority):(.+)$/);
        if (!match) {
          return { handled: true };
        }
        const action = match[1];
        const sessionId = decodeQueueSessionId(match[2] ?? "");
        const pending = takeConflictPending(sessionId);
        if (!pending) {
          await ctx.respond.editMessage({ text: "Сообщение уже обработано или устарело." });
          return { handled: true };
        }

        const chatId = String(pending.context.channel ?? ctx.callback.chatId ?? "");

        if (action === "followup") {
          enqueueFollowup(sessionId, pending);
          await ctx.respond.editMessage({
            text: "📋 Поставил в очередь — выполню после текущего задания.",
          });
          return { handled: true };
        }

        const active = getActiveManusRun(sessionId);
        if (action === "priority" && active) {
          enqueueFollowup(sessionId, {
            message: active.message,
            sessionId: active.sessionId,
            context: active.context,
          });
          active.cancel();
        } else if (action === "cancel" && active) {
          active.cancel();
        }

        await ctx.respond.editMessage({ text: "⏳ Запускаю новое задание…" });

        const result = await executeManusRun({
          wsUrl,
          pending,
          telegramProgress,
          chatId,
          logger: api.logger,
          asyncStart: true,
        });

        await ctx.respond.reply({ text: result.reply.text });
        return { handled: true };
      },
    });

    if (intercept) {
      api.on("before_agent_reply", async (event, ctx) => {
        if (!enabled) return;
        if (skipHeartbeat && ctx.trigger === "heartbeat") return;
        const message = (event.cleanedBody ?? "").trim();
        if (!message) return;

        const sessionId = resolveSessionId(ctx);
        const pending = buildPending(message, ctx);

        if (isManusSessionActive(sessionId)) {
          setConflictPending(sessionId, pending);
          const preview =
            message.length > 120 ? `${message.slice(0, 117).trim()}…` : message;
          const choiceText =
            `⏳ Идёт задание.\n\nНовое сообщение:\n«${escapeHtml(preview)}»\n\nЧто сделать?`;
          const chatId = String(ctx.channelId ?? "");
          if (/^\d+$/.test(chatId)) {
            const markup = queueKeyboardMarkup(sessionId);
            await sendTelegramMessage(chatId, choiceText, markup ? { reply_markup: markup } : undefined);
          }
          return {
            handled: true,
            reply: { text: "⏳ Выбери действие кнопками в сообщении выше." },
            reason: "manus-bridge-queue-choice",
          };
        }

        api.logger.info(
          `manus-bridge: run channel=${ctx.channelId ?? "?"} session=${sessionId}`,
        );

        return executeManusRun({
          wsUrl,
          pending,
          telegramProgress,
          chatId: String(ctx.channelId ?? ""),
          logger: api.logger,
        });
      });
    }

    api.registerHttpRoute({
      path: "/bridge/manus/run",
      auth: "gateway",
      match: "exact",
      gatewayRuntimeScopeSurface: "trusted-operator",
      handler: async (req, res) => {
        if (req.method !== "POST") {
          res.statusCode = 405;
          res.end(JSON.stringify({ error: "method_not_allowed" }));
          return;
        }
        const chunks: Buffer[] = [];
        for await (const chunk of req) {
          chunks.push(Buffer.from(chunk));
        }
        let body: {
          message?: string;
          sessionId?: string;
          context?: Record<string, unknown>;
        };
        try {
          body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        } catch {
          res.statusCode = 400;
          res.end(JSON.stringify({ error: "invalid_json" }));
          return;
        }
        if (!body.message?.trim()) {
          res.statusCode = 400;
          res.end(JSON.stringify({ error: "message_required" }));
          return;
        }

        res.setHeader("Content-Type", "application/x-ndjson");
        res.setHeader("Transfer-Encoding", "chunked");

        const client = getManusBridgeClient(wsUrl);
        const result = await client.run(
          {
            message: body.message,
            sessionId: body.sessionId,
            context: body.context,
          },
          (ev: ManusBridgeEvent) => {
            res.write(`${JSON.stringify({ stream: ev })}\n`);
          },
        );
        res.write(`${JSON.stringify({ result })}\n`);
        res.end();
      },
    });

    api.logger.info(
      `manus-bridge registered (ws=${wsUrl}, intercept=${intercept}, progress=${telegramProgress})`,
    );
  },
});
