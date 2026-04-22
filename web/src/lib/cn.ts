import { clsx, type ClassValue } from "clsx"

/** Tailwind-friendly conditional classname join. */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs)
}
