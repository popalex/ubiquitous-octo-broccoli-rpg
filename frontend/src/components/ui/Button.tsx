import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  children: ReactNode;
};

const variantClass: Record<Variant, string> = {
  primary: "btn-primary",
  secondary: "btn-secondary",
};

export function Button({ variant = "primary", className = "", children, ...rest }: Props) {
  return (
    <button className={`btn ${variantClass[variant]} ${className}`.trim()} {...rest}>
      {children}
    </button>
  );
}
