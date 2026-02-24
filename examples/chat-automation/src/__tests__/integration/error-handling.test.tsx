import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/handlers";
import { installMockEventSource } from "../mocks/sse";
import App from "../../App";

let restoreES: () => void;

beforeEach(() => {
  restoreES = installMockEventSource();
  server.use(
    http.get("/api/sessions/:sid/handoffs", () => {
      return HttpResponse.json([]);
    }),
  );
});

afterEach(() => {
  restoreES();
});

describe("error handling", () => {
  it("shows error message when createSession fails", async () => {
    server.use(
      http.post("/api/sessions/", () => {
        return new HttpResponse("Internal Server Error", { status: 500 });
      }),
    );

    const user = userEvent.setup();
    render(<App />);

    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "start",
    );
    await user.click(screen.getByText("Start"));

    await waitFor(() => {
      expect(screen.getByText(/Failed to create session/)).toBeInTheDocument();
    });
  });

  it("shows error result when executeTurn fails with 500", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Create session first (success)
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "init",
    );
    await user.click(screen.getByText("Start"));
    await waitFor(() => {
      expect(screen.getByText(/Session created/)).toBeInTheDocument();
    });

    // Override turn to fail
    server.use(
      http.post("/api/sessions/:sid/turn", () => {
        return new HttpResponse("Server error", { status: 500 });
      }),
    );

    // Execute turn
    await user.type(
      screen.getByPlaceholderText(/Type your automation intent/),
      "do something",
    );
    await user.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.getByText(/Error:.*API 500/)).toBeInTheDocument();
    });
  });

  it("shows 'Turn was cancelled.' for CancelledError-like errors", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Create session
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "init",
    );
    await user.click(screen.getByText("Start"));
    await waitFor(() => {
      expect(screen.getByText(/Session created/)).toBeInTheDocument();
    });

    // Override turn to throw CancelledError
    server.use(
      http.post("/api/sessions/:sid/turn", () => {
        return new HttpResponse("CancelledError: operation was cancelled", {
          status: 500,
        });
      }),
    );

    await user.type(
      screen.getByPlaceholderText(/Type your automation intent/),
      "try this",
    );
    await user.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.getByText("Turn was cancelled.")).toBeInTheDocument();
    });
  });

  it("shows error when resolveHandoff fails", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Create session
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "init",
    );
    await user.click(screen.getByText("Start"));
    await waitFor(() => {
      expect(screen.getByText(/Session created/)).toBeInTheDocument();
    });

    // Setup handoffs
    server.use(
      http.get("/api/sessions/:sid/handoffs", () => {
        return HttpResponse.json([
          {
            request_id: "h1",
            reason: "CaptchaDetected",
            url: "https://test.com",
            title: "Test",
            message: "Solve CAPTCHA",
            has_screenshot: false,
            created_at: "2026-01-01T00:00:00Z",
          },
        ]);
      }),
    );

    // Execute a turn to trigger handoff fetch
    server.use(
      http.post("/api/sessions/:sid/turn", () => {
        return HttpResponse.json({
          turn_id: "t1",
          turn_num: 1,
          session_id: "sess-abc12345-6789-def0",
          success: true,
          steps_total: 1,
          steps_ok: 1,
          cost_usd: 0.001,
          tokens_used: 100,
          error_msg: null,
          screenshots: [],
          current_url: null,
          pending_handoffs: 1,
        });
      }),
    );

    await user.type(
      screen.getByPlaceholderText(/Type your automation intent/),
      "run",
    );
    await user.click(screen.getByText("Send"));

    // Wait for handoff to appear
    await waitFor(() => {
      expect(screen.getByText("Solve CAPTCHA")).toBeInTheDocument();
    });

    // Make resolve fail
    server.use(
      http.post("/api/sessions/:sid/handoffs/:rid/resolve", () => {
        return new HttpResponse(null, { status: 500 });
      }),
    );

    // Try to resolve
    await user.type(screen.getByPlaceholderText("Enter solution..."), "abc");
    await user.click(screen.getByText("Submit"));

    await waitFor(() => {
      expect(screen.getByText(/Handoff resolve failed/)).toBeInTheDocument();
    });
  });
});
