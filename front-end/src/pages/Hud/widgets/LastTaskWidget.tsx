function relative(ts: number): string {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export default function LastTaskWidget({
  task,
  onClick,
}: {
  task: { label: string; ts: number } | null;
  onClick: () => void;
}) {
  return (
    <div className="hud-widget hud-tr" onClick={onClick}>
      {task ? `Last task: ${task.label} · ${relative(task.ts)}` : "No tasks yet"}
    </div>
  );
}
