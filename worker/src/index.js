const DEFAULT_TOP100_COMMAND = "/roblox-top100";
const DEFAULT_TOP_DAY_COMMAND = "/roblox-top-day";
const DEFAULT_PROJECT_METRICS_COMMAND = "/roblox-project-metrics";
const processedEvents = new Map();
const DEFAULT_DEDUP_KV_BINDING = "EVENT_DEDUP_KV";

export default {
  async fetch(request, env, ctx) {
    return handleRequest(request, env, ctx, fetch);
  },

  async scheduled(controller, env, ctx) {
    return handleScheduled(controller, env, ctx, fetch);
  },
};

export async function handleRequest(request, env, ctx, fetchImpl = fetch) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/health") {
    return jsonResponse({ ok: true, service: "feishu-gh-dispatch" });
  }

  if (request.method !== "POST" || url.pathname !== "/feishu/events") {
    return jsonResponse({ error: "Not found" }, 404);
  }

  const rawBody = await request.text();
  const body = safeParseJson(rawBody);
  if (!body) {
    return jsonResponse({ error: "Invalid JSON" }, 400);
  }

  if (typeof body.challenge === "string") {
    return jsonResponse({ challenge: body.challenge });
  }

  if (!isAllowedToken(body, env)) {
    return jsonResponse({ error: "Forbidden" }, 403);
  }

  const eventId = extractEventId(body);
  if (await isDuplicateEvent(eventId, env)) {
    console.log(JSON.stringify({
      level: "info",
      action: "dedup_hit",
      eventId,
      path: url.pathname,
    }));
    return jsonResponse({ ok: true, duplicate: true });
  }

  const message = extractIncomingMessage(body);
  if (!message) {
    return jsonResponse({ ok: true, ignored: "unsupported_event" });
  }

  if (message.messageType !== "text") {
    return jsonResponse({ ok: true, ignored: "non_text_message" });
  }

  const command = resolveCommand(env, message.text);
  if (!command) {
    return jsonResponse({ ok: true, ignored: "command_mismatch" });
  }

  if (!isAllowedValue(parseCsvSet(env.ALLOWED_CHAT_IDS), message.chatId)) {
    return jsonResponse({ ok: true, ignored: "chat_not_allowed" });
  }

  if (!isAllowedValue(parseCsvSet(env.ALLOWED_OPEN_IDS), message.openId)) {
    return jsonResponse({ ok: true, ignored: "user_not_allowed" });
  }

  console.log(JSON.stringify({
    level: "info",
    action: "event_accepted",
    eventId,
    messageId: extractMessageId(body),
    chatId: message.chatId,
    userId: message.openId || message.userId || "feishu-user",
  }));

  scheduleBackgroundTask(
    ctx,
    processCommandEvent(fetchImpl, env, {
      eventId,
      chatId: message.chatId,
      triggerActor: message.openId || message.userId || "feishu-user",
      reportMode: command.reportMode,
    }),
  );

  return jsonResponse({ ok: true, dispatched: true });
}

export async function handleScheduled(controller, env, ctx, fetchImpl = fetch) {
  const cron = controller?.cron || "";
  console.log(JSON.stringify({
    level: "info",
    action: "schedule_trigger_received",
    cron,
    hasScheduleChatIds: parseCsvList(env.SCHEDULE_CHAT_IDS).length > 0,
  }));

  const trigger = resolveScheduledTrigger(env, cron);
  if (!trigger) {
    return;
  }

  console.log(JSON.stringify({
    level: "info",
    action: "schedule_dispatch_start",
    cron,
    reportMode: trigger.reportMode,
    chatId: trigger.chatId,
  }));

  const task = dispatchWorkflow(fetchImpl, env, trigger, { cron });

  try {
    scheduleBackgroundTask(ctx, task);
    await task;

    console.log(JSON.stringify({
      level: "info",
      action: "schedule_dispatch_success",
      cron,
      reportMode: trigger.reportMode,
      chatId: trigger.chatId,
    }));
  } catch (error) {
    console.error(JSON.stringify({
      level: "error",
      action: "schedule_dispatch_failed",
      cron,
      reportMode: trigger.reportMode,
      chatId: trigger.chatId,
      message: error instanceof Error ? error.message : String(error),
    }));
    throw error;
  }
}

function resolveScheduledTrigger(env, cron) {
  const chatIds = parseCsvList(env.SCHEDULE_CHAT_IDS);
  if ((cron === "0 1 * * *" || cron === "10 1 * * *") && !chatIds.length) {
    console.warn(JSON.stringify({
      level: "warn",
      action: "schedule_skipped_missing_chat_ids",
      cron,
    }));
    return null;
  }

  if (cron === "0 1 * * *") {
    return {
      triggerSource: "cloudflare_cron",
      triggerActor: "cloudflare-cron",
      chatId: chatIds.join(","),
      reportMode: "top_trending_sheet",
    };
  }

  if (cron === "10 1 * * *") {
    return {
      triggerSource: "cloudflare_cron",
      triggerActor: "cloudflare-cron",
      chatId: chatIds.join(","),
      reportMode: "roblox_project_daily_metrics",
    };
  }

  console.warn(JSON.stringify({
    level: "warn",
    action: "schedule_skipped_unknown_cron",
    cron,
  }));
  return null;
}

function safeParseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function isDuplicateEvent(eventId, env) {
  if (!eventId) {
    return false;
  }

  const dedupStore = getDedupStore(env);
  if (dedupStore) {
    const existing = await dedupStore.get(eventId);
    if (existing) {
      return true;
    }

    await dedupStore.put(eventId, String(Date.now()), {
      expirationTtl: getDedupTtlSeconds(env),
    });
    return false;
  }

  pruneProcessedEvents(env);

  if (processedEvents.has(eventId)) {
    return true;
  }

  processedEvents.set(eventId, Date.now());
  console.warn(JSON.stringify({
    level: "warn",
    action: "dedup_store_missing",
    binding: getDedupBindingName(env),
  }));
  return false;
}

function extractEventId(body) {
  return (
    body.header?.event_id ||
    body.event_id ||
    body.event?.message?.message_id ||
    ""
  );
}

function extractMessageId(body) {
  return body.event?.message?.message_id || body.message_id || "";
}

function pruneProcessedEvents(env) {
  const ttlMs = getDedupTtlSeconds(env) * 1000;
  const cutoff = Date.now() - ttlMs;
  for (const [eventId, seenAt] of processedEvents.entries()) {
    if (seenAt < cutoff) {
      processedEvents.delete(eventId);
    }
  }
}

function getDedupTtlSeconds(env) {
  const raw = Number.parseInt(String(env.EVENT_DEDUP_TTL_SECONDS || "600"), 10);
  return Number.isFinite(raw) && raw > 0 ? raw : 600;
}

function getDedupBindingName(env) {
  const raw = String(env.EVENT_DEDUP_KV_BINDING || DEFAULT_DEDUP_KV_BINDING).trim();
  return raw || DEFAULT_DEDUP_KV_BINDING;
}

function getDedupStore(env) {
  const bindingName = getDedupBindingName(env);
  const candidate = env?.[bindingName];
  if (
    candidate &&
    typeof candidate.get === "function" &&
    typeof candidate.put === "function"
  ) {
    return candidate;
  }
  return null;
}

function scheduleBackgroundTask(ctx, task) {
  if (ctx && typeof ctx.waitUntil === "function") {
    ctx.waitUntil(task);
    return;
  }

  void task;
}

function isAllowedToken(body, env) {
  if (!env.FEISHU_VERIFICATION_TOKEN) {
    return true;
  }
  const candidates = [
    body.token,
    body.header?.token,
    body.event?.token,
  ];
  return candidates.includes(env.FEISHU_VERIFICATION_TOKEN);
}

function extractIncomingMessage(body) {
  const event = body.event ?? body;
  const message = event.message ?? {};
  const sender = event.sender ?? {};
  const senderId = sender.sender_id ?? {};
  const chatId = message.chat_id ?? message.chatId ?? "";
  const rawContent = message.content;
  const content = parseMessageContent(rawContent);
  const text = typeof content.text === "string" ? content.text.trim() : "";

  if (!chatId || !text) {
    return null;
  }

  return {
    chatId,
    text,
    messageType: message.message_type ?? message.messageType ?? "",
    userId: senderId.user_id ?? senderId.union_id ?? "",
    openId: senderId.open_id ?? "",
  };
}

function parseMessageContent(content) {
  if (typeof content === "string") {
    try {
      return JSON.parse(content);
    } catch {
      return { text: content };
    }
  }
  if (content && typeof content === "object") {
    return content;
  }
  return {};
}

function parseCsvList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseCsvSet(value) {
  return new Set(parseCsvList(value));
}

function isAllowedValue(allowedSet, candidate) {
  if (!allowedSet.size) {
    return true;
  }
  return allowedSet.has(candidate);
}

async function processCommandEvent(fetchImpl, env, event) {
  console.log(JSON.stringify({
    level: "info",
    action: "dispatch_start",
    eventId: event.eventId,
    chatId: event.chatId,
    triggerActor: event.triggerActor,
  }));

  try {
    await dispatchWorkflow(fetchImpl, env, {
      triggerSource: "feishu_chat_command",
      triggerActor: event.triggerActor,
      chatId: event.chatId,
      reportMode: event.reportMode,
    });

    console.log(JSON.stringify({
      level: "info",
      action: "dispatch_success",
      eventId: event.eventId,
    }));

    await sendAck(fetchImpl, env, event.chatId);

    console.log(JSON.stringify({
      level: "info",
      action: "ack_success",
      eventId: event.eventId,
      chatId: event.chatId,
    }));
  } catch (error) {
    console.error(JSON.stringify({
      level: "error",
      action: "command_event_failed",
      eventId: event.eventId,
      message: error instanceof Error ? error.message : String(error),
    }));
    throw error;
  }
}

async function dispatchWorkflow(fetchImpl, env, trigger, metadata = {}) {
  const workflowFile = env.GH_WORKFLOW_FILE || "roblox_rank_sync.yml";
  const ref = env.GH_REF || "main";
  const url =
    `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}` +
    `/actions/workflows/${workflowFile}/dispatches`;

  const response = await fetchImpl(url, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GH_TOKEN}`,
      "User-Agent": "roblox-top100-feishu-trigger",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref,
      inputs: {
        trigger_source: trigger.triggerSource,
        trigger_actor: trigger.triggerActor,
        chat_id: trigger.chatId,
        report_mode: trigger.reportMode,
      },
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    console.error(JSON.stringify({
      level: "error",
      action: "github_dispatch_failed",
      workflowFile,
      ref,
      triggerSource: trigger.triggerSource,
      reportMode: trigger.reportMode,
      chatId: trigger.chatId,
      cron: metadata.cron || "",
      status: response.status,
      responseText: text.slice(0, 300),
    }));
    throw new Error(`GitHub dispatch failed: ${response.status} ${text.slice(0, 300)}`);
  }
}

function resolveCommand(env, text) {
  const commands = [
    {
      text: env.COMMAND_TEXT || DEFAULT_TOP100_COMMAND,
      reportMode: "top100_message",
    },
    {
      text: env.TOP_DAY_COMMAND_TEXT || DEFAULT_TOP_DAY_COMMAND,
      reportMode: "top_trending_sheet",
    },
    {
      text: env.PROJECT_METRICS_COMMAND_TEXT || DEFAULT_PROJECT_METRICS_COMMAND,
      reportMode: "roblox_project_daily_metrics",
    },
  ];

  return commands.find((command) => command.text === text) || null;
}

async function sendAck(fetchImpl, env, chatId) {
  if (!env.FEISHU_APP_ID || !env.FEISHU_APP_SECRET || !chatId) {
    return;
  }

  const accessToken = await fetchTenantAccessToken(fetchImpl, env);
  const response = await fetchImpl(
    "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        receive_id: chatId,
        msg_type: "text",
        content: JSON.stringify({
          text: "已提交 Roblox 数据抓取任务，稍后会回传结果。",
        }),
      }),
    },
  );

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Feishu ack failed: ${response.status} ${text.slice(0, 300)}`);
  }
}

async function fetchTenantAccessToken(fetchImpl, env) {
  const response = await fetchImpl(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        app_id: env.FEISHU_APP_ID,
        app_secret: env.FEISHU_APP_SECRET,
      }),
    },
  );

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Feishu auth failed: ${response.status} ${text.slice(0, 300)}`);
  }

  const payload = await response.json();
  if (payload.code && payload.code !== 0) {
    throw new Error(`Feishu auth error: ${JSON.stringify(payload)}`);
  }
  if (!payload.tenant_access_token) {
    throw new Error("Feishu auth response missing tenant_access_token");
  }
  return payload.tenant_access_token;
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}
