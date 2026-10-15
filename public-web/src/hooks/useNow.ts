import { useEffect, useState } from "react";

export function useNow(offsetMs: number, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now() + offsetMs);
  useEffect(() => {
    setNow(Date.now() + offsetMs);
    const id = window.setInterval(() => setNow(Date.now() + offsetMs), intervalMs);
    return () => window.clearInterval(id);
  }, [offsetMs, intervalMs]);
  return now;
}
