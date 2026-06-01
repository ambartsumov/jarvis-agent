export type PendingManusRun = {
  message: string;
  sessionId: string;
  context: Record<string, unknown>;
};

export type ActiveManusRun = PendingManusRun & {
  reqId: string;
  cancel: () => void;
};

const activeBySession = new Map<string, ActiveManusRun>();
const followupBySession = new Map<string, PendingManusRun[]>();
const conflictBySession = new Map<string, PendingManusRun>();

export function isManusSessionActive(sessionId: string): boolean {
  return activeBySession.has(sessionId);
}

export function getActiveManusRun(sessionId: string): ActiveManusRun | undefined {
  return activeBySession.get(sessionId);
}

export function setActiveManusRun(sessionId: string, run: ActiveManusRun): void {
  activeBySession.set(sessionId, run);
}

export function clearActiveManusRun(sessionId: string): ActiveManusRun | undefined {
  const run = activeBySession.get(sessionId);
  activeBySession.delete(sessionId);
  return run;
}

export function setConflictPending(sessionId: string, pending: PendingManusRun): void {
  conflictBySession.set(sessionId, pending);
}

export function takeConflictPending(sessionId: string): PendingManusRun | undefined {
  const pending = conflictBySession.get(sessionId);
  conflictBySession.delete(sessionId);
  return pending;
}

export function enqueueFollowup(sessionId: string, pending: PendingManusRun): void {
  const queue = followupBySession.get(sessionId) ?? [];
  queue.push(pending);
  followupBySession.set(sessionId, queue);
}

export function shiftFollowup(sessionId: string): PendingManusRun | undefined {
  const queue = followupBySession.get(sessionId);
  if (!queue || queue.length === 0) {
    followupBySession.delete(sessionId);
    return undefined;
  }
  const next = queue.shift();
  if (!queue.length) {
    followupBySession.delete(sessionId);
  }
  return next;
}

export function buildQueueChoiceInteractive(sessionId: string) {
  const sid = encodeURIComponent(sessionId);
  return {
    blocks: [
      {
        type: "buttons" as const,
        buttons: [
          {
            label: "❌ Отменить текущее",
            value: `manus:queue:cancel:${sid}`,
            style: "danger" as const,
          },
          {
            label: "📋 В очередь",
            value: `manus:queue:followup:${sid}`,
            style: "primary" as const,
          },
          {
            label: "⏩ Сначала это",
            value: `manus:queue:priority:${sid}`,
            style: "success" as const,
          },
        ],
      },
    ],
  };
}

export function decodeQueueSessionId(encoded: string): string {
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}
