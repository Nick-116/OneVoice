import { useCallback, useState } from "react";
import { readStorage, writeStorage } from "../lib/storage";
import { clampTextSize, DEFAULT_TEXT_SIZE } from "../lib/textSize";

export function useTextSize(): [number, (step: number) => void] {
  const [step, setStep] = useState(() => {
    const raw = readStorage("cc.textSize");
    return raw === null ? DEFAULT_TEXT_SIZE : clampTextSize(Number(raw));
  });
  const update = useCallback((next: number) => {
    const value = clampTextSize(next);
    setStep(value);
    writeStorage("cc.textSize", String(value));
  }, []);
  return [step, update];
}
