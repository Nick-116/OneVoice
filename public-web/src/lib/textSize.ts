export const TEXT_SIZE_CLASSES = [
  "text-[1.25rem] leading-[1.6]",
  "text-[1.5rem] leading-[1.6]",
  "text-[1.875rem] leading-[1.55]",
  "text-[2.25rem] leading-[1.5]",
] as const;

export const DEFAULT_TEXT_SIZE = 1;

export function clampTextSize(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_TEXT_SIZE;
  return Math.min(TEXT_SIZE_CLASSES.length - 1, Math.max(0, Math.round(value)));
}
