import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { mockSessionInfo, mockTurnResult, mockHandoffRequest } from "./fixtures";

export const handlers = [
  // Create session
  http.post("/api/sessions/", () => {
    return HttpResponse.json(mockSessionInfo);
  }),

  // Execute turn
  http.post("/api/sessions/:sessionId/turn", () => {
    return HttpResponse.json(mockTurnResult);
  }),

  // Cancel turn
  http.post("/api/sessions/:sessionId/cancel", () => {
    return HttpResponse.json({ status: "ok", message: "Turn cancelled" });
  }),

  // Get screenshot
  http.get("/api/sessions/:sessionId/screenshot", () => {
    return new HttpResponse(new Blob(["fake-image"], { type: "image/png" }), {
      headers: { "Content-Type": "image/png" },
    });
  }),

  // Get handoffs
  http.get("/api/sessions/:sessionId/handoffs", () => {
    return HttpResponse.json([mockHandoffRequest]);
  }),

  // Resolve handoff
  http.post(
    "/api/sessions/:sessionId/handoffs/:requestId/resolve",
    () => {
      return new HttpResponse(null, { status: 200 });
    },
  ),

  // Close session
  http.delete("/api/sessions/:sessionId", () => {
    return new HttpResponse(null, { status: 200 });
  }),
];

export const server = setupServer(...handlers);
