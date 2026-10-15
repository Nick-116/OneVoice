type Key = "cc.lang" | "cc.textSize" | "cc.theme" | "cc.fonts";

export function readStorage(key: Key): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: Key, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode, blocked) */
  }
}
