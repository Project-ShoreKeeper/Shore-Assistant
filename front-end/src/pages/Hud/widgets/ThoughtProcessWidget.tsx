export default function ThoughtProcessWidget({
  thought,
  onClick,
}: {
  thought: string | null;
  onClick: () => void;
}) {
  if (!thought) return null;
  return (
    <div className="hud-widget hud-bl" onClick={onClick}>
      Thought: {thought}
    </div>
  );
}
