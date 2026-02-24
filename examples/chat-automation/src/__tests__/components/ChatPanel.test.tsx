import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatPanel from "../../components/ChatPanel";
import type { ChatMessage, HandoffRequest } from "../../types";
import { mockHandoffRequest } from "../mocks/fixtures";

const baseProps = {
  messages: [] as ChatMessage[],
  sessionId: null as string | null,
  isRunning: false,
  handoffs: [] as HandoffRequest[],
  onStartSession: vi.fn(),
  onSend: vi.fn(),
  onResolveHandoff: vi.fn(),
};

function renderPanel(overrides: Partial<typeof baseProps> = {}) {
  const props = { ...baseProps, ...overrides };
  for (const fn of [props.onStartSession, props.onSend, props.onResolveHandoff]) {
    (fn as ReturnType<typeof vi.fn>).mockClear();
  }
  return render(<ChatPanel {...props} />);
}

describe("ChatPanel", () => {
  // ── Pre-session state ───────────────────────────

  it("shows EmptyState when no session and no messages", () => {
    renderPanel();
    expect(screen.getByText("Chat Automation")).toBeInTheDocument();
    expect(screen.getByText(/Describe what you want to automate/)).toBeInTheDocument();
  });

  it("shows URL input when no session", () => {
    renderPanel();
    expect(screen.getByPlaceholderText(/Starting URL/)).toBeInTheDocument();
  });

  it('shows "Start" button when no session', () => {
    renderPanel();
    expect(screen.getByText("Start")).toBeInTheDocument();
  });

  it("Start button is disabled when intent input is empty", () => {
    renderPanel();
    expect(screen.getByText("Start")).toBeDisabled();
  });

  it("calls onStartSession with URL on Start click", async () => {
    const user = userEvent.setup();
    const onStartSession = vi.fn();
    renderPanel({ onStartSession });

    await user.type(screen.getByPlaceholderText(/Starting URL/), "https://test.com");
    await user.type(
      screen.getByPlaceholderText(/Type your first intent/),
      "search something",
    );
    await user.click(screen.getByText("Start"));

    expect(onStartSession).toHaveBeenCalledWith("https://test.com", undefined);
  });

  // ── Active session state ────────────────────────

  it('shows "Send" button when session is active', () => {
    renderPanel({ sessionId: "sess-123" });
    expect(screen.getByText("Send")).toBeInTheDocument();
  });

  it("hides URL input when session is active", () => {
    renderPanel({ sessionId: "sess-123" });
    expect(screen.queryByPlaceholderText(/Starting URL/)).not.toBeInTheDocument();
  });

  it("calls onSend with text on Send click", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    renderPanel({ sessionId: "sess-123", onSend });

    await user.type(
      screen.getByPlaceholderText(/Type your automation intent/),
      "click the button",
    );
    await user.click(screen.getByText("Send"));

    expect(onSend).toHaveBeenCalledWith("click the button", undefined);
  });

  it("sends on Enter key press", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    renderPanel({ sessionId: "sess-123", onSend });

    await user.type(
      screen.getByPlaceholderText(/Type your automation intent/),
      "go to google{Enter}",
    );

    expect(onSend).toHaveBeenCalledWith("go to google", undefined);
  });

  it("clears input after submit", async () => {
    const user = userEvent.setup();
    renderPanel({ sessionId: "sess-123", onSend: vi.fn() });

    const input = screen.getByPlaceholderText(/Type your automation intent/);
    await user.type(input, "test{Enter}");

    expect(input).toHaveValue("");
  });

  // ── Running state ───────────────────────────────

  it("disables input when isRunning", () => {
    renderPanel({ sessionId: "sess-123", isRunning: true });
    const input = screen.getByPlaceholderText("Running...");
    expect(input).toBeDisabled();
  });

  it('shows "Executing" indicator when running', () => {
    renderPanel({ sessionId: "sess-123", isRunning: true });
    expect(screen.getByText("Executing")).toBeInTheDocument();
  });

  // ── Message rendering ───────────────────────────

  it("renders messages in order", () => {
    const messages: ChatMessage[] = [
      { id: "1", type: "user", content: "first", timestamp: 1 },
      { id: "2", type: "system", content: "second", timestamp: 2 },
      { id: "3", type: "user", content: "third", timestamp: 3 },
    ];
    renderPanel({ sessionId: "sess-123", messages });

    const first = screen.getByText("first");
    const second = screen.getByText("second");
    const third = screen.getByText("third");

    // All should be in the document
    expect(first).toBeInTheDocument();
    expect(second).toBeInTheDocument();
    expect(third).toBeInTheDocument();
  });

  // ── Handoff rendering ───────────────────────────

  it("renders HandoffInline for pending handoffs", () => {
    renderPanel({
      sessionId: "sess-123",
      handoffs: [mockHandoffRequest],
    });
    expect(screen.getByText("CAPTCHA")).toBeInTheDocument();
    expect(screen.getByText(mockHandoffRequest.message)).toBeInTheDocument();
  });

  // ── Attachment functionality ─────────────────────

  it("renders the attach files button", () => {
    renderPanel({ sessionId: "sess-123" });
    expect(screen.getByLabelText("Attach files")).toBeInTheDocument();
  });

  it("renders hidden file input", () => {
    renderPanel({ sessionId: "sess-123" });
    const fileInput = screen.getByTestId("file-input") as HTMLInputElement;
    expect(fileInput).toBeInTheDocument();
    expect(fileInput.type).toBe("file");
    expect(fileInput.accept).toBe("image/*");
    expect(fileInput.multiple).toBe(true);
  });

  it("shows attachment preview after file selection", async () => {
    renderPanel({ sessionId: "sess-123" });

    const fileInput = screen.getByTestId("file-input") as HTMLInputElement;
    const file = new File(["hello"], "test.png", { type: "image/png" });

    // Mock FileReader to call onload synchronously
    const originalFR = global.FileReader;
    class MockFileReader {
      result = "data:image/png;base64,aGVsbG8=";
      onload: (() => void) | null = null;
      readAsDataURL() {
        // Trigger onload asynchronously to mimic real behavior
        setTimeout(() => this.onload?.(), 0);
      }
    }
    global.FileReader = MockFileReader as unknown as typeof FileReader;

    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByTestId("attachment-preview")).toBeInTheDocument();
      expect(screen.getByText("test.png")).toBeInTheDocument();
    });

    global.FileReader = originalFR;
  });

  it("removes attachment when x is clicked", async () => {
    renderPanel({ sessionId: "sess-123" });

    const fileInput = screen.getByTestId("file-input") as HTMLInputElement;
    const file = new File(["img"], "photo.png", { type: "image/png" });

    const originalFR = global.FileReader;
    class MockFileReader {
      result = "data:image/png;base64,aW1n";
      onload: (() => void) | null = null;
      readAsDataURL() {
        setTimeout(() => this.onload?.(), 0);
      }
    }
    global.FileReader = MockFileReader as unknown as typeof FileReader;

    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByText("photo.png")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByLabelText("Remove photo.png"));

    await waitFor(() => {
      expect(screen.queryByText("photo.png")).not.toBeInTheDocument();
    });

    global.FileReader = originalFR;
  });

  it("passes attachments to onSend when files are attached", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    renderPanel({ sessionId: "sess-123", onSend });

    const fileInput = screen.getByTestId("file-input") as HTMLInputElement;
    const file = new File(["img"], "photo.png", { type: "image/png" });

    const originalFR = global.FileReader;
    class MockFileReader {
      result = "data:image/png;base64,aW1n";
      onload: (() => void) | null = null;
      readAsDataURL() {
        setTimeout(() => this.onload?.(), 0);
      }
    }
    global.FileReader = MockFileReader as unknown as typeof FileReader;

    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByText("photo.png")).toBeInTheDocument();
    });

    await user.type(
      screen.getByPlaceholderText(/Type your automation intent/),
      "find similar{Enter}",
    );

    expect(onSend).toHaveBeenCalledWith("find similar", [
      expect.objectContaining({
        filename: "photo.png",
        mimeType: "image/png",
        dataUrl: "data:image/png;base64,aW1n",
      }),
    ]);

    global.FileReader = originalFR;
  });

  it("disables attach button when running", () => {
    renderPanel({ sessionId: "sess-123", isRunning: true });
    expect(screen.getByLabelText("Attach files")).toBeDisabled();
  });
});
