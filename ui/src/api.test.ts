import { test } from "node:test";
import assert from "node:assert/strict";
import { endpoint, request } from "./api.ts";
test("the host prefix keeps the backend API namespace", () => {
  assert.equal(endpoint("", "compare"), "/api/compare");
  assert.equal(
    endpoint("/api/calculator/", "config"),
    "/api/calculator/api/config",
  );
});
test("withheld backend errors remain errors", async () => {
  const prior = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ error: "Event order is withheld." }), {
      status: 422,
      headers: { "content-type": "application/json" },
    });
  try {
    await assert.rejects(
      request("", "calculate", new AbortController().signal, {}),
      /Event order is withheld/,
    );
  } finally {
    globalThis.fetch = prior;
  }
});
