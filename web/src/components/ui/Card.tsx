import { cn } from "../../lib/cn"
import type { HTMLAttributes, PropsWithChildren } from "react"

export function Card({
  className,
  children,
  ...rest
}: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card text-card-fg shadow-sm",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  className,
  children,
  ...rest
}: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div className={cn("px-4 py-3 border-b border-border", className)} {...rest}>
      {children}
    </div>
  )
}

export function CardBody({
  className,
  children,
  ...rest
}: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) {
  return (
    <div className={cn("px-4 py-3", className)} {...rest}>
      {children}
    </div>
  )
}
