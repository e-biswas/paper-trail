import type { ButtonHTMLAttributes, PropsWithChildren } from "react"
import { cn } from "../../lib/cn"

type Variant = "primary" | "ghost" | "outline"
type Size = "sm" | "md"

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-status-checking text-white hover:bg-status-checking/90 disabled:opacity-50 shadow-sm",
  ghost: "hover:bg-accent/60",
  outline: "border border-border hover:bg-accent/50",
}

const SIZE: Record<Size, string> = {
  sm: "h-7 px-2 text-xs rounded-md",
  md: "h-9 px-3 text-sm rounded-md",
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: PropsWithChildren<
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }
>) {
  return (
    <button
      className={cn(
        "inline-flex items-center gap-1.5 font-medium transition-colors disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}
