import type { ReactElement } from "react";
import type { Health, SandboxState, UsagePayload } from "../../api/types";
import type { HealthStatus } from "../../hooks/use-health";
import { formatTokens, shortModelName } from "../../lib/format";
import { useOptionalSession } from "../../state/session-context";
import type { StreamConnection } from "../../state/use-session-stream";

interface StatusBarProps {
  healthStatus: HealthStatus;
}

const SANDBOX_LABELS: Record<SandboxState, string> = {
  ready: "Sandbox ready",
  unavailable: "Sandbox unavailable",
};

const CONNECTION_LABELS: Record<StreamConnection, string> = {
  connecting: "Event stream connecting",
  open: "Event stream connected",
  reconnecting: "Event stream reconnecting",
};

interface UsageReadoutProps {
  usage: UsagePayload | null;
  health: Health | null;
}

function UsageReadout({ usage, health }: UsageReadoutProps): ReactElement {
  const contextLimit = usage?.context_limit_tokens ?? health?.context_limit_tokens ?? null;
  const contextUsed = usage === null ? "0" : formatTokens(usage.context_used_tokens);
  return (
    <>
      <span className="status-item">
        {usage === null ? "No speed reading yet" : `${usage.tokens_per_second.toFixed(1)} tokens/s`}
      </span>
      <span className="status-item">
        Context {contextUsed} / {contextLimit === null ? "unknown" : formatTokens(contextLimit)}
      </span>
    </>
  );
}

interface HealthReadoutProps {
  health: Health;
}

function ModelReadout({ health }: HealthReadoutProps): ReactElement {
  if (!health.is_healthy) {
    return (
      <span
        className="status-item status-problem"
        role="status"
        title="Foundry Local is not running. It is started again automatically when you send a message or index a folder."
      >
        Model service stopped
      </span>
    );
  }
  const orchestratorModelId = health.roles.orchestrator;
  return (
    <span className="status-item">
      Model{" "}
      {orchestratorModelId === undefined ? (
        "not loaded"
      ) : (
        <span className="model-tag" title={orchestratorModelId}>
          {shortModelName(orchestratorModelId)}
        </span>
      )}
    </span>
  );
}

function HealthReadout({ health }: HealthReadoutProps): ReactElement {
  return (
    <>
      <ModelReadout health={health} />
      <span
        className="status-item"
        title={
          health.is_offline
            ? "No network use: web search is off and the model runs on this device."
            : "Web search is on: queries may leave this device."
        }
      >
        {health.is_offline ? "Local only" : "Online: web search on"}
      </span>
      <span className={`status-item status-sandbox-${health.sandbox_state}`}>
        {SANDBOX_LABELS[health.sandbox_state]}
      </span>
    </>
  );
}

/** The footer: loaded model, generation speed, context use, network and sandbox state. */
export function StatusBar({ healthStatus }: StatusBarProps): ReactElement {
  const session = useOptionalSession();
  const { health, hasChecked } = healthStatus;

  return (
    <footer className="status-bar" aria-label="Status">
      {health === null ? (
        <span
          className={hasChecked ? "status-item status-problem" : "status-item muted"}
          role="status"
        >
          {hasChecked ? "Orchestrator unreachable" : "Checking orchestrator…"}
        </span>
      ) : (
        <HealthReadout health={health} />
      )}
      <UsageReadout usage={session?.state.usage ?? null} health={health} />
      {session !== null && (
        <span className="status-item">{CONNECTION_LABELS[session.connection]}</span>
      )}
    </footer>
  );
}
