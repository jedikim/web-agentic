import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/handlers";
import {
  mockSessionInfo,
  mockProgressEvent,
  mockHandoffEvent,
  mockTurnCompleteEvent,
} from "../mocks/fixtures";
import { installMockEventSource, lastMockEventSource } from "../mocks/sse";
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

async function createSession() {
  const user = userEvent.setup();
  render(<App />);

  await user.type(
    screen.getByPlaceholderText(/Type your first intent/),
    "init",
  );
  await user.click(screen.getByText("Start"));

  await waitFor(() => {
    expect(screen.getByText(/Session created/)).toBeInTheDocument();
  });
}

describe("SSE events", () => {
  it("renders step_started as running step log", async () => {
    await createSession();

    act(() => {
      lastMockEventSource!.emitProgress({
        ...mockProgressEvent,
        session_id: mockSessionInfo.session_id,
        event: "step_started",
        message: "Navigating to page",
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/Step 1\/3: Navigating to page/)).toBeInTheDocument();
    });
    // Running icon ▶
    expect(screen.getByText("\u25B6")).toBeInTheDocument();
  });

  it("renders step_completed as ok step log", async () => {
    await createSession();

    act(() => {
      lastMockEventSource!.emitProgress({
        ...mockProgressEvent,
        session_id: mockSessionInfo.session_id,
        event: "step_completed",
        message: "Clicked button",
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/Step 1\/3: Clicked button/)).toBeInTheDocument();
    });
    // OK icon ✓
    expect(screen.getByText("\u2713")).toBeInTheDocument();
  });

  it("renders step_failed as fail step log", async () => {
    await createSession();

    act(() => {
      lastMockEventSource!.emitProgress({
        ...mockProgressEvent,
        session_id: mockSessionInfo.session_id,
        event: "step_failed",
        message: "Element not found",
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/Step 1\/3: Element not found/)).toBeInTheDocument();
    });
    // Fail icon ✗
    expect(screen.getByText("\u2717")).toBeInTheDocument();
  });

  it("renders handoff_requested as handoff message", async () => {
    await createSession();

    act(() => {
      lastMockEventSource!.emitHandoff({
        ...mockHandoffEvent,
        session_id: mockSessionInfo.session_id,
      });
    });

    await waitFor(() => {
      expect(screen.getByText("CAPTCHA detected on page")).toBeInTheDocument();
    });
    expect(screen.getByText("Handoff Required")).toBeInTheDocument();
  });

  it("shows 'Turn cancelled.' on cancelled turn complete", async () => {
    await createSession();

    act(() => {
      lastMockEventSource!.emitTurnComplete({
        ...mockTurnCompleteEvent,
        session_id: mockSessionInfo.session_id,
        cancelled: true,
      });
    });

    await waitFor(() => {
      expect(screen.getByText("Turn cancelled.")).toBeInTheDocument();
    });
  });

  it("ignores events from other sessions", async () => {
    await createSession();

    act(() => {
      lastMockEventSource!.emitProgress({
        ...mockProgressEvent,
        session_id: "different-session-id",
        event: "step_started",
        message: "Should not appear",
      });
    });

    // Give it a moment to potentially process
    await vi.advanceTimersByTimeAsync?.(100).catch(() => {});
    // Use a short wait then check it's NOT there
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Should not appear")).not.toBeInTheDocument();
  });
});
