import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/handlers";
import { mockFailedTurnResult } from "../mocks/fixtures";
import { installMockEventSource } from "../mocks/sse";
import App from "../../App";

let restoreES: () => void;

beforeEach(() => {
  restoreES = installMockEventSource();
  // Empty handoffs by default for lifecycle tests
  server.use(
    http.get("/api/sessions/:sid/handoffs", () => {
      return HttpResponse.json([]);
    }),
  );
});

afterEach(() => {
  restoreES();
});

describe("session lifecycle", () => {
  it("creates a session and shows system messages", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Type intent and click Start
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "search for cats",
    );
    await user.click(screen.getByText("Start"));

    // Should show "Starting session..." and then "Session created"
    await waitFor(() => {
      expect(screen.getByText("Starting session...")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(
        screen.getByText(/Session created: sess-abc/),
      ).toBeInTheDocument();
    });
  });

  it("executes a turn and shows user + result messages", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Create session first
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "init",
    );
    await user.click(screen.getByText("Start"));

    await waitFor(() => {
      expect(screen.getByText(/Session created/)).toBeInTheDocument();
    });

    // Now send a turn
    await user.type(
      screen.getByPlaceholderText(/Type your automation intent/),
      "click buy button",
    );
    await user.click(screen.getByText("Send"));

    // User message should appear
    expect(screen.getByText("click buy button")).toBeInTheDocument();

    // Result message should appear (success)
    await waitFor(() => {
      expect(screen.getByText(/Done: 3\/3 steps, \$0\.0042/)).toBeInTheDocument();
    });
  });

  it("closes session and resets state", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Create session
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "start",
    );
    await user.click(screen.getByText("Start"));
    await waitFor(() => {
      expect(screen.getByText(/Session created/)).toBeInTheDocument();
    });

    // Close session
    await user.click(screen.getByText("Close"));

    await waitFor(() => {
      expect(screen.getByText("Session closed.")).toBeInTheDocument();
    });

    // Should show Start button again (no session)
    expect(screen.getByText("Start")).toBeInTheDocument();
  });

  it("starts new session and clears messages", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Create session
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "start",
    );
    await user.click(screen.getByText("Start"));
    await waitFor(() => {
      expect(screen.getByText(/Session created/)).toBeInTheDocument();
    });

    // New session
    await user.click(screen.getByText("New"));

    // Messages should be cleared
    await waitFor(() => {
      expect(screen.queryByText(/Session created/)).not.toBeInTheDocument();
    });

    // EmptyState should reappear
    expect(screen.getByText("Chat Automation")).toBeInTheDocument();
  });

  it("shows failed turn result with error message", async () => {
    server.use(
      http.post("/api/sessions/:sid/turn", () => {
        return HttpResponse.json(mockFailedTurnResult);
      }),
    );

    const user = userEvent.setup();
    render(<App />);

    // Create session
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "start",
    );
    await user.click(screen.getByText("Start"));
    await waitFor(() => {
      expect(screen.getByText(/Session created/)).toBeInTheDocument();
    });

    // Execute turn
    await user.type(
      screen.getByPlaceholderText(/Type your automation intent/),
      "click missing",
    );
    await user.click(screen.getByText("Send"));

    // Failed result
    await waitFor(() => {
      expect(
        screen.getByText(/Failed: 1\/3 steps\. Element not found/),
      ).toBeInTheDocument();
    });
  });
});
