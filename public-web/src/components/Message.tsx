import type { ReactNode } from "react";

interface Props {
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}

export function Message({ title, children, className = "" }: Props) {
  return (
    <div className={`mx-auto flex max-w-xl flex-col items-center gap-4 px-6 py-12 text-center ${className}`}>
      <h2 className="text-balance font-semibold text-gray-900">{title}</h2>
      {children}
    </div>
  );
}

export function WaitingDots() {
  return (
    <span aria-hidden="true" className="flex gap-2">
      <span className="h-3 w-3 rounded-full bg-gray-400 motion-safe:animate-bounce" />
      <span className="h-3 w-3 rounded-full bg-gray-400 motion-safe:animate-bounce motion-safe:[animation-delay:150ms]" />
      <span className="h-3 w-3 rounded-full bg-gray-400 motion-safe:animate-bounce motion-safe:[animation-delay:300ms]" />
    </span>
  );
}
