type Props = {
  label?: string;
  className?: string;
};

export function Spinner({ label = "Loading...", className = "" }: Props) {
  return (
    <div className={`hub-loading ${className}`.trim()} role="status" aria-live="polite">
      <span className="hub-loading-rune" aria-hidden="true">✦</span>
      <p>{label}</p>
    </div>
  );
}
