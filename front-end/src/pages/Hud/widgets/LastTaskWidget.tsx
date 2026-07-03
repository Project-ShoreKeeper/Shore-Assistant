import type { HudTask } from "@Shore/services/hud-bridge.service";
import type { HudActionRequest } from "@Shore/services/hud-actions";
import HudPopover from "../HudPopover";

function relative(ts: number): string {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export default function LastTaskWidget({
  task,
  active,
  expanded,
  hasPending,
  onToggle,
  sendAction,
}: {
  task: HudTask | null;
  active: boolean;
  expanded: boolean;
  hasPending: boolean;
  onToggle: () => void;
  sendAction: (action: HudActionRequest) => string;
}) {
  return (
    <>
      <button
        type="button"
        className="hud-widget hud-tr"
        data-hud-widget="task"
        aria-expanded={expanded}
        onClick={() => {
          if (active && task) onToggle();
        }}
      >
        {task
          ? `Last task: ${task.tool} · ${relative(task.ts)}`
          : "No tasks yet"}
      </button>
      {active && expanded && task && (
        <HudPopover
          title="Latest task"
          className="hud-task-popover"
          onClose={onToggle}
        >
          <dl className="hud-task-details">
            <div><dt>Tool</dt><dd>{task.tool}</dd></div>
            <div><dt>Status</dt><dd>{task.status}</dd></div>
            <div>
              <dt>Time</dt>
              <dd>{new Date(task.ts).toLocaleTimeString()}</dd>
            </div>
          </dl>
          <p className="hud-task-summary">{task.summary}</p>
          <div className="hud-popover-actions">
            <button
              type="button"
              disabled={hasPending}
              onClick={() => sendAction({
                action: "focus_main",
                payload: {
                  destination: "chat",
                  messageId: task.messageId,
                },
              })}
            >
              Open in chat
            </button>
          </div>
        </HudPopover>
      )}
    </>
  );
}
