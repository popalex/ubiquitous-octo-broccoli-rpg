import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Boom({ shouldThrow }: { shouldThrow: boolean }): React.ReactElement {
  if (shouldThrow) {
    throw new Error("kaboom");
  }
  return <div>all good</div>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs caught errors to console.error; silence it for clean output.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <Boom shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("all good")).toBeInTheDocument();
  });

  it("shows the fallback with the error message when a child throws", () => {
    render(
      <ErrorBoundary>
        <Boom shouldThrow={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("kaboom")).toBeInTheDocument();
  });

  it("renders a custom fallback when provided", async () => {
    const user = userEvent.setup();
    const reset = vi.fn();
    render(
      <ErrorBoundary fallback={(error, doReset) => (
        <button onClick={() => { reset(); doReset(); }}>retry {error.message}</button>
      )}>
        <Boom shouldThrow={true} />
      </ErrorBoundary>,
    );
    const button = screen.getByRole("button", { name: /retry kaboom/ });
    expect(button).toBeInTheDocument();
    await user.click(button);
    expect(reset).toHaveBeenCalled();
  });
});
