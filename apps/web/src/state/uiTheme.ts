import { reactive } from "vue";

export type ThemeMode = "dark" | "light";

const STORAGE_KEY = "agentic-sdlc-theme";

function readStoredTheme(): ThemeMode {
  if (typeof window === "undefined") {
    return "dark";
  }
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "light" ? "light" : "dark";
}

export const uiTheme = reactive({
  mode: readStoredTheme() as ThemeMode,
});

export function applyTheme(mode: ThemeMode) {
  uiTheme.mode = mode;
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", mode);
  }
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, mode);
  }
}

export function initializeTheme() {
  applyTheme(readStoredTheme());
}

export function toggleTheme() {
  applyTheme(uiTheme.mode === "dark" ? "light" : "dark");
}
