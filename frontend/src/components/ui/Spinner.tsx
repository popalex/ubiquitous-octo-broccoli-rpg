import { LoaderCircle } from "lucide-react";

type Props = {
  label?: string;
  className?: string;
};

export function Spinner({ label = "Loading...", className = "" }: Props) {
  return (
    <div className={`hub-loading ${className}`.trim()} role="status" aria-live="polite">
      <LoaderCircle className="hub-loading-rune" size={32} aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}
