import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HandoffInline from "../../components/HandoffInline";
import { mockHandoffRequest, mockHandoffRequestAction } from "../mocks/fixtures";

describe("HandoffInline", () => {
  it("shows CAPTCHA label for CaptchaDetected reason", () => {
    render(<HandoffInline handoff={mockHandoffRequest} onResolve={vi.fn()} />);
    expect(screen.getByText("CAPTCHA")).toBeInTheDocument();
  });

  it("shows Action Required for other reasons", () => {
    render(<HandoffInline handoff={mockHandoffRequestAction} onResolve={vi.fn()} />);
    expect(screen.getByText("Action Required")).toBeInTheDocument();
  });

  it("displays message, url, and title", () => {
    render(<HandoffInline handoff={mockHandoffRequest} onResolve={vi.fn()} />);
    expect(screen.getByText(mockHandoffRequest.message)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(mockHandoffRequest.url))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(mockHandoffRequest.title))).toBeInTheDocument();
  });

  it("Submit button is disabled when input is empty", () => {
    render(<HandoffInline handoff={mockHandoffRequest} onResolve={vi.fn()} />);
    expect(screen.getByText("Submit")).toBeDisabled();
  });

  it("enables Submit button with input text", async () => {
    const user = userEvent.setup();
    render(<HandoffInline handoff={mockHandoffRequest} onResolve={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Enter solution..."), "abc123");
    expect(screen.getByText("Submit")).toBeEnabled();
  });

  it("calls onResolve with requestId and trimmed input on Submit", async () => {
    const user = userEvent.setup();
    const onResolve = vi.fn();
    render(<HandoffInline handoff={mockHandoffRequest} onResolve={onResolve} />);

    await user.type(screen.getByPlaceholderText("Enter solution..."), "  solved  ");
    await user.click(screen.getByText("Submit"));

    expect(onResolve).toHaveBeenCalledWith(mockHandoffRequest.request_id, "solved");
  });

  it("calls onResolve on Enter key", async () => {
    const user = userEvent.setup();
    const onResolve = vi.fn();
    render(<HandoffInline handoff={mockHandoffRequest} onResolve={onResolve} />);

    const input = screen.getByPlaceholderText("Enter solution...");
    await user.type(input, "done{Enter}");

    expect(onResolve).toHaveBeenCalledWith(mockHandoffRequest.request_id, "done");
  });

  it("becomes disabled after submission", async () => {
    const user = userEvent.setup();
    render(<HandoffInline handoff={mockHandoffRequest} onResolve={vi.fn()} />);

    await user.type(screen.getByPlaceholderText("Enter solution..."), "x");
    await user.click(screen.getByText("Submit"));

    // After submitting, the button should show "..." and be disabled
    expect(screen.getByText("...")).toBeDisabled();
    expect(screen.getByPlaceholderText("Enter solution...")).toBeDisabled();
  });
});
