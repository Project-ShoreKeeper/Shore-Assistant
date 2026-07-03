export default function AnswerWidget({
  answer,
  onClick,
}: {
  answer: string | null;
  onClick: () => void;
}) {
  if (!answer) return null;
  return (
    <div className="hud-widget hud-bl" onClick={onClick}>
      Answer: {answer}
    </div>
  );
}
