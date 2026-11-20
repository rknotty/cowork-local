import type { ReactElement } from "react";
import { listSkills } from "../../api/api-client";
import { useApiResource } from "../../hooks/use-api-resource";

/** A read-only list of the skills the orchestrator has available. */
export function SkillsBrowser(): ReactElement {
  const { resource: skills } = useApiResource(listSkills);

  if (skills === null) {
    return <p className="rail-note">Loading skills</p>;
  }
  if (skills.length === 0) {
    return <p className="rail-note">No skills are installed.</p>;
  }
  return (
    <dl className="skill-list">
      {skills.map((skill) => (
        <div key={skill.name} className="skill">
          <dt>{skill.name}</dt>
          <dd>{skill.description}</dd>
        </div>
      ))}
    </dl>
  );
}
