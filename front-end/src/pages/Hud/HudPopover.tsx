export default function HudPopover({
  title,
  className,
  onClose,
  children,
}: {
  title: string;
  className: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <section
      className={`hud-widget-popover ${className}`}
      role="dialog"
      aria-label={title}
    >
      <header className="hud-popover-header">
        <strong>{title}</strong>
        <button
          type="button"
          className="hud-popover-close"
          aria-label={`Close ${title}`}
          onClick={onClose}
        >
          ×
        </button>
      </header>
      {children}
    </section>
  );
}
