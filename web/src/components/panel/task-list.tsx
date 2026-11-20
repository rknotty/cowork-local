import type { ReactElement } from "react";
import type { TaskStatus } from "../../api/types";
import { useSession } from "../../state/session-context";

const STATUS_LABELS: Record<TaskStatus, string> = {
  pending: "Pending",
  in_progress: "In progress",
  done: "Done",
};

/** The agent's current task list, exactly as last sent by `task_update`. */
export function TaskList(): ReactElement {
  const { state } = useSession();
  if (state.tasks.length === 0) {
    return <p className="empty-state">The agent has not set out any tasks yet.</p>;
  }
  return (
    <ol className="task-list">
      {state.tasks.map((task) => (
        <li key={task.id} className={`task task-${task.status}`}>
          <span className="task-title">{task.title}</span>
          <span className={`badge badge-task-${task.status}`}>{STATUS_LABELS[task.status]}</span>
        </li>
      ))}
    </ol>
  );
}
