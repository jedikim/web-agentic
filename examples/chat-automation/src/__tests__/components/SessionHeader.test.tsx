import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SessionHeader from "../../components/SessionHeader";

const baseProps = {
  sessionId: null as string | null,
  headless: true,
  onToggleHeadless: vi.fn(),
  isRunning: false,
  onCancel: vi.fn(),
  onClose: vi.fn(),
  onNewSession: vi.fn(),
  totalCost: 0,
  turnCount: 0,
};

function renderHeader(overrides: Partial<typeof baseProps> = {}) {
  const props = { ...baseProps, ...overrides };
  // Reset mocks
  for (const fn of [props.onToggleHeadless, props.onCancel, props.onClose, props.onNewSession]) {
    (fn as ReturnType<typeof vi.fn>).mockClear();
  }
  return render(<SessionHeader {...props} />);
}

describe("SessionHeader", () => {
  it("shows branding", () => {
    renderHeader();
    expect(screen.getByText("WA")).toBeInTheDocument();
    expect(screen.getByText("Web-Agentic Chat")).toBeInTheDocument();
  });

  it("shows Headless toggle when no session", () => {
    renderHeader({ headless: true });
    expect(screen.getByText("Headless")).toBeInTheDocument();
  });

  it("shows Headful when headless is false", () => {
    renderHeader({ headless: false });
    expect(screen.getByText("Headful")).toBeInTheDocument();
  });

  it("calls onToggleHeadless when clicking the toggle", async () => {
    const user = userEvent.setup();
    const fn = vi.fn();
    renderHeader({ onToggleHeadless: fn });
    await user.click(screen.getByText("Headless"));
    expect(fn).toHaveBeenCalledOnce();
  });

  it("shows session ID, Turns, Cost when session is active", () => {
    renderHeader({
      sessionId: "sess-abc12345-6789-def0",
      turnCount: 3,
      totalCost: 0.0126,
    });
    expect(screen.getByText("sess-abc1234...")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("$0.0126")).toBeInTheDocument();
  });

  it('shows "Running" status when isRunning', () => {
    renderHeader({ sessionId: "sess-123", isRunning: true });
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it('shows "Idle" status when not running', () => {
    renderHeader({ sessionId: "sess-123", isRunning: false });
    expect(screen.getByText("Idle")).toBeInTheDocument();
  });

  it("shows Cancel button when running", async () => {
    const user = userEvent.setup();
    const fn = vi.fn();
    renderHeader({ sessionId: "sess-123", isRunning: true, onCancel: fn });
    const btn = screen.getByText("Cancel");
    expect(btn).toBeInTheDocument();
    await user.click(btn);
    expect(fn).toHaveBeenCalledOnce();
  });

  it("shows New and Close buttons when idle with session", async () => {
    const user = userEvent.setup();
    const onNew = vi.fn();
    const onClose = vi.fn();
    renderHeader({
      sessionId: "sess-123",
      isRunning: false,
      onNewSession: onNew,
      onClose: onClose,
    });
    await user.click(screen.getByText("New"));
    expect(onNew).toHaveBeenCalledOnce();
    await user.click(screen.getByText("Close"));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("hides headless toggle when session is active", () => {
    renderHeader({ sessionId: "sess-123" });
    expect(screen.queryByText("Headless")).not.toBeInTheDocument();
  });
});
