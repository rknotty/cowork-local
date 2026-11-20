import { useId } from "react";
import type { ReactElement } from "react";
import type { Health } from "../../api/types";
import type { ThemeChoice } from "../../hooks/use-theme";
import { formatTokens } from "../../lib/format";

interface SettingsPanelProps {
  health: Health | null;
  theme: ThemeChoice;
  onThemeChange: (theme: ThemeChoice) => void;
}

const THEME_LABELS: Record<ThemeChoice, string> = {
  system: "Match system",
  light: "Light",
  dark: "Dark",
};

const THEME_CHOICES = Object.keys(THEME_LABELS) as ThemeChoice[];

interface ModelRolesProps {
  health: Health;
}

function ModelRoles({ health }: ModelRolesProps): ReactElement {
  return (
    <dl className="fact-list">
      {Object.entries(health.roles).map(([role, modelId]) => (
        <div key={role} className="fact-pair">
          <dt>{role}</dt>
          <dd>
            <code className="fact-code">{modelId}</code>
          </dd>
        </div>
      ))}
      <div className="fact-pair">
        <dt>Context limit</dt>
        <dd>{formatTokens(health.context_limit_tokens)} tokens</dd>
      </div>
    </dl>
  );
}

/**
 * Display settings held in this browser, plus a read-only view of the model
 * roles the orchestrator reports. Model configuration itself lives server-side.
 */
export function SettingsPanel({ health, theme, onThemeChange }: SettingsPanelProps): ReactElement {
  const themeId = useId();
  return (
    <div className="rail-section-body">
      <div className="stacked-form">
        <label htmlFor={themeId}>Colour theme</label>
        <select
          id={themeId}
          value={theme}
          onChange={(event) => onThemeChange(event.target.value as ThemeChoice)}
        >
          {THEME_CHOICES.map((choice) => (
            <option key={choice} value={choice}>
              {THEME_LABELS[choice]}
            </option>
          ))}
        </select>
      </div>
      <h3 className="rail-subheading">Models in use</h3>
      {health === null ? (
        <p className="rail-note">Not available while the orchestrator is unreachable.</p>
      ) : (
        <ModelRoles health={health} />
      )}
    </div>
  );
}
