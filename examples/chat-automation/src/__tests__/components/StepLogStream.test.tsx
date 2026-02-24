import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StepLogStream from "../../components/StepLogStream";

describe("StepLogStream", () => {
  it("shows running status with ▶ icon", () => {
    render(<StepLogStream content="Navigating" meta={{ status: "running", method: "LLM" }} />);
    expect(screen.getByText("\u25B6")).toBeInTheDocument(); // ▶
    expect(screen.getByText("Navigating")).toBeInTheDocument();
  });

  it("shows ok status with ✓ icon", () => {
    render(<StepLogStream content="Done" meta={{ status: "ok", method: "Cache" }} />);
    expect(screen.getByText("\u2713")).toBeInTheDocument(); // ✓
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("shows fail status with ✗ icon", () => {
    render(<StepLogStream content="Failed" meta={{ status: "fail", method: "Vision" }} />);
    expect(screen.getByText("\u2717")).toBeInTheDocument(); // ✗
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("shows method badge", () => {
    render(<StepLogStream content="test" meta={{ status: "ok", method: "Vision" }} />);
    expect(screen.getByText("Vision")).toBeInTheDocument();
  });

  it("omits method badge when method is empty", () => {
    const { container } = render(<StepLogStream content="test" meta={{ status: "ok" }} />);
    // No badge element with method text — the only text elements should be the icon and content
    const spans = container.querySelectorAll("span");
    const texts = Array.from(spans).map((s) => s.textContent);
    // Should have icon but no method badge text
    expect(texts).not.toContain("LLM");
    expect(texts).not.toContain("Cache");
  });

  it("defaults to running when no status provided", () => {
    render(<StepLogStream content="working" />);
    expect(screen.getByText("\u25B6")).toBeInTheDocument();
  });
});
