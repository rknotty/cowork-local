import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  HEALTH_FIXTURE,
  installMockOrchestrator,
  MockEventSource,
} from "../../test/mock-orchestrator";
import { renderInSession } from "../../test/render-helpers";
import { StatusBar } from "./status-bar";

describe("StatusBar", () => {
  beforeEach(() => {
    installMockOrchestrator();
  });

  it("should show Local only, with an explanation, when health reports is_offline", () => {
    render(<StatusBar healthStatus={{ health: HEALTH_FIXTURE, hasChecked: true }} />);

    expect(screen.getByText("Local only")).toHaveAttribute(
      "title",
      expect.stringContaining("No network use") as string
    );
    expect(screen.queryByText(/Online/)).not.toBeInTheDocument();
  });

  it("should say web search is on when health reports it is not offline", () => {
    const health = { ...HEALTH_FIXTURE, is_offline: false };

    render(<StatusBar healthStatus={{ health, hasChecked: true }} />);

    expect(screen.getByText("Online: web search on")).toBeInTheDocument();
  });

  it("should show the orchestrator model with its full ID on hover, and the sandbox state", () => {
    const health = { ...HEALTH_FIXTURE, sandbox_state: "unavailable" as const };

    render(<StatusBar healthStatus={{ health, hasChecked: true }} />);

    expect(screen.getByText("example-model-14b")).toHaveAttribute("title", "example-model-14b:2");
    expect(screen.getByText("Sandbox unavailable")).toBeInTheDocument();
    expect(screen.getByText("Context 0 / 32,768")).toBeInTheDocument();
  });

  it("should say the orchestrator is unreachable when a health check has failed", () => {
    render(<StatusBar healthStatus={{ health: null, hasChecked: true }} />);

    expect(screen.getByText("Orchestrator unreachable")).toBeInTheDocument();
    expect(screen.getByText("Context 0 / unknown")).toBeInTheDocument();
  });

  it("should say the model service has stopped, and that it restarts on use", () => {
    const health = { ...HEALTH_FIXTURE, is_healthy: false, roles: {} };

    render(<StatusBar healthStatus={{ health, hasChecked: true }} />);

    expect(screen.getByText("Model service stopped")).toHaveAttribute(
      "title",
      expect.stringContaining("started again automatically") as string
    );
    expect(screen.queryByText(/not loaded/)).not.toBeInTheDocument();
  });

  it("should show speed and context from the latest usage event", () => {
    renderInSession(<StatusBar healthStatus={{ health: HEALTH_FIXTURE, hasChecked: true }} />);

    act(() =>
      MockEventSource.latest().emit("usage", {
        model_id: "example-model-14b:2",
        prompt_tokens: 1200,
        completion_tokens: 300,
        duration_ms: 12000,
        tokens_per_second: 25.04,
        context_used_tokens: 1500,
        context_limit_tokens: 16384,
      })
    );

    expect(screen.getByText("25.0 tokens/s")).toBeInTheDocument();
    expect(screen.getByText("Context 1,500 / 16,384")).toBeInTheDocument();
  });
});
