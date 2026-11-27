import { useEffect, useState } from "react";
import { useStored } from "./api";

export type ThemePref = "dark" | "light" | "system";
export type Density = "comfortable" | "compact";
const mq = () => window.matchMedia("(prefers-color-scheme: light)");

/** Applies the chosen look to the page. The inline script in index.html does the same before first paint, so nothing flashes. */
export function useAppearance() {
  const [theme, setTheme] = useStored<ThemePref>("theme", "dark");
  const [density, setDensity] = useStored<Density>("density", "comfortable");
  const [mode, setMode] = useState<"light" | "dark">(() => (document.documentElement.dataset.mode === "light" ? "light" : "dark"));
  useEffect(() => {
    const apply = () => { const m = theme === "system" ? (mq().matches ? "light" : "dark") : theme; document.documentElement.dataset.mode = m; setMode(m); };
    apply();
    if (theme !== "system") return;
    const m = mq(); m.addEventListener("change", apply);
    return () => m.removeEventListener("change", apply);
  }, [theme]);
  useEffect(() => { if (density === "compact") document.documentElement.dataset.density = "compact"; else delete document.documentElement.dataset.density; }, [density]);
  return { theme, setTheme, density, setDensity, mode };
}
