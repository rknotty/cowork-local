import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./error-boundary";

function BrokenComponent(): ReactElement {
  throw new Error("internal detail that must not be shown");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React reports caught render errors to the console; keep test output clean.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("should render children when nothing fails", () => {
    render(
      <ErrorBoundary>
        <p>Working content</p>
      </ErrorBoundary>
    );

    expect(screen.getByText("Working content")).toBeInTheDocument();
  });

  it("should show a recoverable message instead of a blank page when a child throws", () => {
    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.getByRole("button", { name: "Reload the page" })).toBeInTheDocument();
    expect(screen.queryByText(/internal detail/)).not.toBeInTheDocument();
  });
});
