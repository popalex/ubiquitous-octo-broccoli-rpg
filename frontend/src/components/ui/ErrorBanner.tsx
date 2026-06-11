type Props = {
  message: string;
  onRetry?: () => void;
};

export function ErrorBanner({ message, onRetry }: Props) {
  return (
    <div className="hub-error" role="alert">
      <p>⚠ {message}</p>
      {onRetry && (
        <button className="btn btn-secondary" type="button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
