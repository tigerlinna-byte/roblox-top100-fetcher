import test from "node:test";
import assert from "node:assert/strict";

import { handleRequest, handleScheduled } from "../src/index.js";

class MemoryKvStore {
  constructor() {
    this.store = new Map();
  }

  async get(key) {
    return this.store.has(key) ? this.store.get(key) : null;
  }

  async put(key, value) {
    this.store.set(key, value);
  }
}

function buildEnv(overrides = {}) {
  return {
    GH_TOKEN: "gh-test",
    GH_OWNER: "octo",
    GH_REPO: "roblox-top100-fetcher",
    GH_WORKFLOW_FILE: "roblox_rank_sync.yml",
    GH_REF: "main",
    FEISHU_APP_ID: "cli_xxx",
    FEISHU_APP_SECRET: "secret",
    FEISHU_VERIFICATION_TOKEN: "verify-me",
    ALLOWED_CHAT_IDS: "oc_test_chat",
    ALLOWED_OPEN_IDS: "ou_test_user",
    EVENT_DEDUP_KV: new MemoryKvStore(),
    ...overrides,
  };
}

function buildRequest(payload) {
  return new Request("https://example.com/feishu/events", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

function buildCtx() {
  const tasks = [];
  return {
    tasks,
    waitUntil(promise) {
      tasks.push(promise);
    },
  };
}

test("responds to Feishu challenge", async () => {
  const response = await handleRequest(
    buildRequest({ challenge: "abc123" }),
    buildEnv(),
    null,
    async () => {
      throw new Error("fetch should not be called");
    },
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { challenge: "abc123" });
});

test("dispatches workflow and sends ack for allowed command", async () => {
  const calls = [];
  const ctx = buildCtx();
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });

    if (String(url).includes("/dispatches")) {
      return new Response(null, { status: 204 });
    }

    if (String(url).includes("/tenant_access_token/internal")) {
      return Response.json({ code: 0, tenant_access_token: "tenant-token" });
    }

    if (String(url).includes("/im/v1/messages")) {
      return Response.json({ code: 0, data: { message_id: "om_test" } });
    }

    throw new Error(`Unexpected fetch ${url}`);
  };

  const response = await handleRequest(
    buildRequest({
      header: { token: "verify-me", event_id: "evt_1" },
      event: {
        sender: {
          sender_id: {
            open_id: "ou_test_user",
          },
        },
        message: {
          message_id: "om_message_1",
          chat_id: "oc_test_chat",
          message_type: "text",
          content: JSON.stringify({ text: "/roblox-top100" }),
        },
      },
    }),
    buildEnv(),
    ctx,
    fetchImpl,
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, dispatched: true });
  assert.equal(ctx.tasks.length, 1);

  await Promise.all(ctx.tasks);
  assert.equal(calls.length, 3);

  const dispatchCall = calls[0];
  assert.match(String(dispatchCall.url), /\/dispatches$/);
  const dispatchBody = JSON.parse(dispatchCall.init.body);
  assert.equal(dispatchBody.ref, "main");
  assert.equal(dispatchBody.inputs.trigger_source, "feishu_chat_command");
  assert.equal(dispatchBody.inputs.trigger_actor, "ou_test_user");
  assert.equal(dispatchBody.inputs.chat_id, "oc_test_chat");
  assert.equal(dispatchBody.inputs.report_mode, "top100_message");

  const ackCall = calls[2];
  const ackBody = JSON.parse(ackCall.init.body);
  assert.equal(ackBody.receive_id, "oc_test_chat");
});

test("dispatches project metrics workflow for /roblox-project-metrics", async () => {
  const calls = [];
  const ctx = buildCtx();
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });

    if (String(url).includes("/dispatches")) {
      return new Response(null, { status: 204 });
    }

    if (String(url).includes("/tenant_access_token/internal")) {
      return Response.json({ code: 0, tenant_access_token: "tenant-token" });
    }

    if (String(url).includes("/im/v1/messages")) {
      return Response.json({ code: 0, data: { message_id: "om_test" } });
    }

    throw new Error(`Unexpected fetch ${url}`);
  };

  const response = await handleRequest(
    buildRequest({
      header: { token: "verify-me", event_id: "evt_project_metrics" },
      event: {
        sender: {
          sender_id: {
            open_id: "ou_test_user",
          },
        },
        message: {
          message_id: "om_message_project_metrics",
          chat_id: "oc_test_chat",
          message_type: "text",
          content: JSON.stringify({ text: "/roblox-project-metrics" }),
        },
      },
    }),
    buildEnv(),
    ctx,
    fetchImpl,
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, dispatched: true });
  await Promise.all(ctx.tasks);

  const dispatchBody = JSON.parse(calls[0].init.body);
  assert.equal(dispatchBody.inputs.report_mode, "roblox_project_daily_metrics");
  assert.equal(dispatchBody.inputs.chat_id, "oc_test_chat");
});

test("dispatches Top Trending workflow for /roblox-top-day", async () => {
  const calls = [];
  const ctx = buildCtx();
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });

    if (String(url).includes("/dispatches")) {
      return new Response(null, { status: 204 });
    }

    if (String(url).includes("/tenant_access_token/internal")) {
      return Response.json({ code: 0, tenant_access_token: "tenant-token" });
    }

    if (String(url).includes("/im/v1/messages")) {
      return Response.json({ code: 0, data: { message_id: "om_test" } });
    }

    throw new Error(`Unexpected fetch ${url}`);
  };

  const response = await handleRequest(
    buildRequest({
      header: { token: "verify-me", event_id: "evt_top_day" },
      event: {
        sender: {
          sender_id: {
            open_id: "ou_test_user",
          },
        },
        message: {
          message_id: "om_message_top_day",
          chat_id: "oc_test_chat",
          message_type: "text",
          content: JSON.stringify({ text: "/roblox-top-day" }),
        },
      },
    }),
    buildEnv(),
    ctx,
    fetchImpl,
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, dispatched: true });
  await Promise.all(ctx.tasks);

  const dispatchBody = JSON.parse(calls[0].init.body);
  assert.equal(dispatchBody.inputs.report_mode, "top_trending_sheet");
  assert.equal(dispatchBody.inputs.chat_id, "oc_test_chat");
});

test("ignores command from unauthorized chat", async () => {
  let called = false;
  const response = await handleRequest(
    buildRequest({
      header: { token: "verify-me", event_id: "evt_2" },
      event: {
        sender: {
          sender_id: {
            open_id: "ou_test_user",
          },
        },
        message: {
          chat_id: "oc_other_chat",
          message_type: "text",
          content: JSON.stringify({ text: "/roblox-top100" }),
        },
      },
    }),
    buildEnv(),
    null,
    async () => {
      called = true;
      return new Response(null, { status: 204 });
    },
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, ignored: "chat_not_allowed" });
  assert.equal(called, false);
});

test("deduplicates repeated event ids with persistent store", async () => {
  const calls = [];
  const ctx1 = buildCtx();
  const ctx2 = buildCtx();
  const env = buildEnv();
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });

    if (String(url).includes("/dispatches")) {
      return new Response(null, { status: 204 });
    }

    if (String(url).includes("/tenant_access_token/internal")) {
      return Response.json({ code: 0, tenant_access_token: "tenant-token" });
    }

    if (String(url).includes("/im/v1/messages")) {
      return Response.json({ code: 0, data: { message_id: "om_test" } });
    }

    throw new Error(`Unexpected fetch ${url}`);
  };

  const payload = {
    header: { token: "verify-me", event_id: "evt_duplicate" },
    event: {
      sender: {
        sender_id: {
          open_id: "ou_test_user",
        },
      },
      message: {
        message_id: "om_message_same",
        chat_id: "oc_test_chat",
        message_type: "text",
        content: JSON.stringify({ text: "/roblox-top100" }),
      },
    },
  };

  const firstResponse = await handleRequest(buildRequest(payload), env, ctx1, fetchImpl);
  assert.equal(firstResponse.status, 200);
  assert.deepEqual(await firstResponse.json(), { ok: true, dispatched: true });
  assert.equal(ctx1.tasks.length, 1);
  await Promise.all(ctx1.tasks);
  assert.equal(calls.length, 3);

  const secondResponse = await handleRequest(buildRequest(payload), env, ctx2, fetchImpl);
  assert.equal(secondResponse.status, 200);
  assert.deepEqual(await secondResponse.json(), { ok: true, duplicate: true });
  assert.equal(ctx2.tasks.length, 0);
  assert.equal(calls.length, 3);
});

test("dispatches scheduled top_trending_sheet workflow to configured chats", async () => {
  const calls = [];
  const ctx = buildCtx();
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });
    if (String(url).includes("/dispatches")) {
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected fetch ${url}`);
  };

  await handleScheduled(
    { cron: "0 1 * * *" },
    buildEnv({ SCHEDULE_CHAT_IDS: "oc_chat_a,oc_chat_b" }),
    ctx,
    fetchImpl,
  );

  assert.equal(calls.length, 1);
  const dispatchBody = JSON.parse(calls[0].init.body);
  assert.equal(dispatchBody.inputs.report_mode, "top_trending_sheet");
  assert.equal(dispatchBody.inputs.trigger_source, "cloudflare_cron");
  assert.equal(dispatchBody.inputs.chat_id, "oc_chat_a,oc_chat_b");
});

test("dispatches scheduled project metrics workflow", async () => {
  const calls = [];
  const ctx = buildCtx();
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init });
    if (String(url).includes("/dispatches")) {
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected fetch ${url}`);
  };

  await handleScheduled(
    { cron: "10 1 * * *" },
    buildEnv({ SCHEDULE_CHAT_IDS: "oc_chat_a,oc_chat_b" }),
    ctx,
    fetchImpl,
  );

  assert.equal(calls.length, 1);
  const dispatchBody = JSON.parse(calls[0].init.body);
  assert.equal(dispatchBody.inputs.report_mode, "roblox_project_daily_metrics");
  assert.equal(dispatchBody.inputs.trigger_source, "cloudflare_cron");
  assert.equal(dispatchBody.inputs.chat_id, "oc_chat_a,oc_chat_b");
});

test("skips scheduled top_trending dispatch when no schedule chats configured", async () => {
  let called = false;
  await handleScheduled(
    { cron: "0 1 * * *" },
    buildEnv({ SCHEDULE_CHAT_IDS: "" }),
    buildCtx(),
    async () => {
      called = true;
      return new Response(null, { status: 204 });
    },
  );

  assert.equal(called, false);
});

test("skips scheduled project metrics dispatch when no schedule chats configured", async () => {
  let called = false;
  await handleScheduled(
    { cron: "10 1 * * *" },
    buildEnv({ SCHEDULE_CHAT_IDS: "" }),
    buildCtx(),
    async () => {
      called = true;
      return new Response(null, { status: 204 });
    },
  );

  assert.equal(called, false);
});

test("skips scheduled dispatch for unknown cron", async () => {
  let called = false;
  await handleScheduled(
    { cron: "0 19 * * *" },
    buildEnv({ SCHEDULE_CHAT_IDS: "oc_chat_a" }),
    buildCtx(),
    async () => {
      called = true;
      return new Response(null, { status: 204 });
    },
  );

  assert.equal(called, false);
});
