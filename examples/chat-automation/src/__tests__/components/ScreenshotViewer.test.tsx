import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ScreenshotViewer from "../../components/ScreenshotViewer";

describe("ScreenshotViewer", () => {
  it("renders thumbnail image", () => {
    render(<ScreenshotViewer src="blob:mock/123" />);
    const img = screen.getByAltText("Page screenshot");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", "blob:mock/123");
  });

  it("shows 'Click to expand' on hover", () => {
    render(<ScreenshotViewer src="blob:mock/123" />);
    expect(screen.getByText("Click to expand")).toBeInTheDocument();
  });

  it("opens modal on click", async () => {
    const user = userEvent.setup();
    render(<ScreenshotViewer src="blob:mock/123" />);

    await user.click(screen.getByAltText("Page screenshot"));

    // Modal should show full image
    const fullImg = screen.getByAltText("Page screenshot (full)");
    expect(fullImg).toBeInTheDocument();
    expect(fullImg).toHaveAttribute("src", "blob:mock/123");
  });

  it("shows ESC button in modal", async () => {
    const user = userEvent.setup();
    render(<ScreenshotViewer src="blob:mock/123" />);

    await user.click(screen.getByAltText("Page screenshot"));
    expect(screen.getByText("ESC")).toBeInTheDocument();
  });

  it("closes modal on ESC button click", async () => {
    const user = userEvent.setup();
    render(<ScreenshotViewer src="blob:mock/123" />);

    await user.click(screen.getByAltText("Page screenshot"));
    expect(screen.getByAltText("Page screenshot (full)")).toBeInTheDocument();

    await user.click(screen.getByText("ESC"));
    expect(screen.queryByAltText("Page screenshot (full)")).not.toBeInTheDocument();
  });
});
