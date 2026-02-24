import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ChatMessageView from "../../components/ChatMessage";
import type { ChatMessage } from "../../types";

function msg(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: "msg-1",
    type: "system",
    content: "test content",
    timestamp: Date.now(),
    ...overrides,
  };
}

describe("ChatMessage", () => {
  it("renders user message right-aligned", () => {
    const { container } = render(
      <ChatMessageView message={msg({ type: "user", content: "hello" })} />,
    );
    expect(screen.getByText("hello")).toBeInTheDocument();
    // User messages use justify-end
    expect(container.querySelector(".justify-end")).not.toBeNull();
  });

  it("renders system message centered", () => {
    const { container } = render(
      <ChatMessageView message={msg({ type: "system", content: "Session created" })} />,
    );
    expect(screen.getByText("Session created")).toBeInTheDocument();
    expect(container.querySelector(".justify-center")).not.toBeNull();
  });

  it("renders step_log via StepLogStream", () => {
    render(
      <ChatMessageView
        message={msg({ type: "step_log", content: "Step 1/3: Nav", meta: { status: "ok", method: "LLM" } })}
      />,
    );
    expect(screen.getByText("Step 1/3: Nav")).toBeInTheDocument();
    expect(screen.getByText("LLM")).toBeInTheDocument();
  });

  it("renders successful result with checkmark", () => {
    render(
      <ChatMessageView
        message={msg({ type: "result", content: "Done: 3/3 steps", meta: { success: true } })}
      />,
    );
    expect(screen.getByText("Done: 3/3 steps")).toBeInTheDocument();
    // ✓ character
    expect(screen.getByText("\u2713")).toBeInTheDocument();
  });

  it("renders failed result with cross mark", () => {
    render(
      <ChatMessageView
        message={msg({ type: "result", content: "Failed: 1/3", meta: { success: false } })}
      />,
    );
    expect(screen.getByText("Failed: 1/3")).toBeInTheDocument();
    // ✗ character
    expect(screen.getByText("\u2717")).toBeInTheDocument();
  });

  it("renders screenshot via ScreenshotViewer", () => {
    render(
      <ChatMessageView
        message={msg({ type: "screenshot", content: "blob:mock/123" })}
      />,
    );
    const img = screen.getByAltText("Page screenshot");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "blob:mock/123");
  });

  it("renders handoff with reason", () => {
    render(
      <ChatMessageView
        message={msg({
          type: "handoff",
          content: "CAPTCHA detected",
          meta: { reason: "CaptchaDetected" },
        })}
      />,
    );
    expect(screen.getByText("Handoff Required")).toBeInTheDocument();
    expect(screen.getByText("CAPTCHA detected")).toBeInTheDocument();
    expect(screen.getByText(/CaptchaDetected/)).toBeInTheDocument();
  });

  // ── Attachment rendering ──────────────────────────

  it("renders image thumbnails when user message has attachments", () => {
    render(
      <ChatMessageView
        message={msg({
          type: "user",
          content: "find similar",
          meta: {
            attachments: [
              {
                filename: "photo.png",
                mimeType: "image/png",
                dataUrl: "data:image/png;base64,abc123",
                size: 1024,
              },
            ],
          },
        })}
      />,
    );
    expect(screen.getByText("find similar")).toBeInTheDocument();
    const img = screen.getByAltText("photo.png");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "data:image/png;base64,abc123");
  });

  it("renders user message without attachments when none provided", () => {
    render(
      <ChatMessageView message={msg({ type: "user", content: "hello" })} />,
    );
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.queryByTestId("message-attachments")).not.toBeInTheDocument();
  });
});
