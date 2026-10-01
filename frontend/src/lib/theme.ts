import { useCallback, useState } from "react";

export type Theme = "dark" | "light";
const KEY = "lucia-theme";

function read(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(read);
  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* private mode: the theme just won't persist */
    }
    setTheme(next);
  }, [theme]);
  return { theme, toggle };
}
