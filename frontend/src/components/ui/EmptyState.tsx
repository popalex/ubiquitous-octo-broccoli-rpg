import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
  className?: string;
};

export function EmptyState({ children, className = "" }: Props) {
  return (
    <div className={`empty-state ${className}`.trim()} role="status">
      {children}
    </div>
  );
}
