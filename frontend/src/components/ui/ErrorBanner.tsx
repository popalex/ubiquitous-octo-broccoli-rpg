import { TriangleAlert } from "lucide-react";

type Props = {
  message: string;
  onRetry?: () => void;
};

export function ErrorBanner({ message, onRetry }: Props) {
  return (
    <div className="hub-error" role="alert">
      <p>
        <TriangleAlert className="inline-icon" /> {message}
      </p>
      {onRetry && (
        <button className="btn btn-secondary" type="button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
