import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./mocks/handlers";
import { mockSessionInfo, mockTurnResult, mockHandoffRequest } from "./mocks/fixtures";
import {
  createSession,
  executeTurn,
  cancelTurn,
  getScreenshot,
  getHandoffs,
  resolveHandoff,
  closeSession,
} from "../api";

describe("API client", () => {
  // ── createSession ────────────────────────────────

  it("createSession(true) posts headless:true, url:null", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/sessions/", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(mockSessionInfo);
      }),
    );

    const result = await createSession(true);
    expect(result).toEqual(mockSessionInfo);
    expect(capturedBody).toEqual({ headless: true, url: null });
  });

  it("createSession(false, url) includes url in body", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/sessions/", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(mockSessionInfo);
      }),
    );

    await createSession(false, "https://example.com");
    expect(capturedBody).toEqual({ headless: false, url: "https://example.com" });
  });

  // ── executeTurn ──────────────────────────────────

  it("executeTurn sends POST with intent", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/sessions/:sid/turn", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(mockTurnResult);
      }),
    );

    const result = await executeTurn("sess-123", "search for cats");
    expect(result).toEqual(mockTurnResult);
    expect(capturedBody).toEqual({ intent: "search for cats" });
  });

  it("executeTurn includes attachments in body when provided", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/sessions/:sid/turn", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(mockTurnResult);
      }),
    );

    await executeTurn("sess-123", "find similar", [
      {
        filename: "photo.png",
        mimeType: "image/png",
        dataUrl: "data:image/png;base64,abc123",
        size: 1024,
      },
    ]);

    expect(capturedBody).toEqual({
      intent: "find similar",
      attachments: [
        {
          filename: "photo.png",
          mime_type: "image/png",
          base64_data: "abc123",
        },
      ],
    });
  });

  it("executeTurn omits attachments field when none provided", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/sessions/:sid/turn", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json(mockTurnResult);
      }),
    );

    await executeTurn("sess-123", "just text");
    expect(capturedBody).toEqual({ intent: "just text" });
  });

  // ── cancelTurn ───────────────────────────────────

  it("cancelTurn sends POST and returns status", async () => {
    const result = await cancelTurn("sess-123");
    expect(result).toEqual({ status: "ok", message: "Turn cancelled" });
  });

  // ── getScreenshot ────────────────────────────────

  it("getScreenshot returns a blob URL", async () => {
    const url = await getScreenshot("sess-123");
    expect(url).toMatch(/^blob:/);
  });

  it("getScreenshot throws on non-OK response", async () => {
    server.use(
      http.get("/api/sessions/:sid/screenshot", () => {
        return new HttpResponse(null, { status: 404 });
      }),
    );

    await expect(getScreenshot("sess-123")).rejects.toThrow("Screenshot failed");
  });

  // ── getHandoffs ──────────────────────────────────

  it("getHandoffs returns HandoffRequest[]", async () => {
    const result = await getHandoffs("sess-123");
    expect(result).toEqual([mockHandoffRequest]);
  });

  // ── resolveHandoff ───────────────────────────────

  it("resolveHandoff sends action_taken in body", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/sessions/:sid/handoffs/:rid/resolve", async ({ request }) => {
        capturedBody = await request.json();
        return new HttpResponse(null, { status: 200 });
      }),
    );

    await resolveHandoff("sess-123", "handoff-001", "solved captcha");
    expect(capturedBody).toEqual({ action_taken: "solved captcha" });
  });

  it("resolveHandoff throws on failure", async () => {
    server.use(
      http.post("/api/sessions/:sid/handoffs/:rid/resolve", () => {
        return new HttpResponse(null, { status: 500 });
      }),
    );

    await expect(resolveHandoff("sess-123", "h1", "x")).rejects.toThrow(
      "Resolve handoff failed",
    );
  });

  // ── closeSession ─────────────────────────────────

  it("closeSession sends DELETE", async () => {
    // Should not throw on 200
    await closeSession("sess-123");
  });

  it("closeSession throws on failure", async () => {
    server.use(
      http.delete("/api/sessions/:sid", () => {
        return new HttpResponse(null, { status: 500 });
      }),
    );

    await expect(closeSession("sess-123")).rejects.toThrow("Close session failed");
  });

  // ── Error handling ───────────────────────────────

  it("throws with status code on 500 error", async () => {
    server.use(
      http.post("/api/sessions/", () => {
        return new HttpResponse("Internal Server Error", { status: 500 });
      }),
    );

    await expect(createSession(true)).rejects.toThrow("API 500");
  });

  it("throws with body text on 404 error", async () => {
    server.use(
      http.post("/api/sessions/:sid/turn", () => {
        return new HttpResponse("Session not found", { status: 404 });
      }),
    );

    await expect(executeTurn("bad-id", "test")).rejects.toThrow("Session not found");
  });
});
