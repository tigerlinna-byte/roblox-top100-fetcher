const DEFAULT_COMMAND = "/roblox-top100";
const processedEvents = new Map();

export default {
  async fetch(request, env, ctx) {
    return handleRequest(request, env, ctx, fetch);
  },
};

export async function handleRequest(request, env, _ctx, fetchImpl = fetch) {
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

  if (isDuplicateEvent(body, env)) {
    return jsonResponse({ ok: true, duplicate: true });
  }

  const message = extractIncomingMessage(body);
  if (!message) {
    return jsonResponse({ ok: true, ignored: "unsupported_event" });
  }

  if (message.messageType !== "text") {
    return jsonResponse({ ok: true, ignored: "non_text_message" });
  }

  if (message.text !== (env.COMMAND_TEXT || DEFAULT_COMMAND)) {
    return jsonResponse({ ok: true, ignored: "command_mismatch" });
  }

  if (!isAllowedValue(parseCsvSet(env.ALLOWED_CHAT_IDS), message.chatId)) {
    return jsonResponse({ ok: true, ignored: "chat_not_allowed" });
  }

  if (!isAllowedValue(parseCsvSet(env.ALLOWED_OPEN_IDS), message.openId)) {
    return jsonResponse({ ok: true, ignored: "user_not_allowed" });
  }

  await dispatchWorkflow(fetchImpl, env, {
    triggerSource: "feishu_chat_command",
    triggerActor: message.openId || message.userId || "feishu-user",
  });

  await sendAck(fetchImpl, env, message.chatId);

  return jsonResponse({ ok: true, dispatched: true });
}

function safeParseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isDuplicateEvent(body, env) {
  const eventId = extractEventId(body);
  if (!eventId) {
    return false;
  }

  pruneProcessedEvents(env);

  if (processedEvents.has(eventId)) {
    return true;
  }

  processedEvents.set(eventId, Date.now());
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

function pruneProcessedEvents(env) {
  const ttlMs = getDedupTtlMs(env);
  const cutoff = Date.now() - ttlMs;
  for (const [eventId, seenAt] of processedEvents.entries()) {
    if (seenAt < cutoff) {
      processedEvents.delete(eventId);
    }
  }
}

function getDedupTtlMs(env) {
  const raw = Number.parseInt(String(env.EVENT_DEDUP_TTL_SECONDS || "600"), 10);
  const ttlSeconds = Number.isFinite(raw) && raw > 0 ? raw : 600;
  return ttlSeconds * 1000;
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

function parseCsvSet(value) {
  return new Set(
    String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
}

function isAllowedValue(allowedSet, candidate) {
  if (!allowedSet.size) {
    return true;
  }
  return allowedSet.has(candidate);
}

async function dispatchWorkflow(fetchImpl, env, trigger) {
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
      },
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`GitHub dispatch failed: ${response.status} ${text.slice(0, 300)}`);
  }
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
          text: "已提交 Roblox 排行榜抓取任务，稍后会回传结果。",
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
