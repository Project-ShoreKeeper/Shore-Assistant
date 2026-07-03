export default function AnswerWidget({
  answer,
  onClick,
}: {
  answer: string | null;
  onClick: () => void;
}) {
  if (!answer) return null;
  return (
    <button
      type="button"
      className="hud-widget hud-bl"
      onClick={onClick}
    >
      Answer: {answer}
    </button>
  );
}
