import test from "node:test";
import assert from "node:assert/strict";

import { handleRequest } from "../src/index.js";

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
      header: { token: "verify-me" },
      event: {
        sender: {
          sender_id: {
            open_id: "ou_test_user",
          },
        },
        message: {
          chat_id: "oc_test_chat",
          message_type: "text",
          content: JSON.stringify({ text: "/roblox-top100" }),
        },
      },
    }),
    buildEnv(),
    null,
    fetchImpl,
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, dispatched: true });
  assert.equal(calls.length, 3);

  const dispatchCall = calls[0];
  assert.match(String(dispatchCall.url), /\/dispatches$/);
  const dispatchBody = JSON.parse(dispatchCall.init.body);
  assert.equal(dispatchBody.ref, "main");
  assert.equal(dispatchBody.inputs.trigger_source, "feishu_chat_command");
  assert.equal(dispatchBody.inputs.trigger_actor, "ou_test_user");

  const ackCall = calls[2];
  const ackBody = JSON.parse(ackCall.init.body);
  assert.equal(ackBody.receive_id, "oc_test_chat");
});

test("ignores command from unauthorized chat", async () => {
  let called = false;
  const response = await handleRequest(
    buildRequest({
      header: { token: "verify-me" },
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
