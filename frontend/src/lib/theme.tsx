import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

type Theme = 'light' | 'dark';
const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({ theme: 'light', toggle: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.classList.contains('dark') ? 'dark' : 'light');

  // Apply synchronously during render so chart colours read the new tokens.
  document.documentElement.classList.toggle('dark', theme === 'dark');
  useEffect(() => {
    try { localStorage.setItem('finsight-theme', theme); } catch { /* storage unavailable */ }
  }, [theme]);

  const toggle = useCallback(() => setTheme(t => (t === 'dark' ? 'light' : 'dark')), []);
  return <ThemeCtx.Provider value={{ theme, toggle }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);

/** Resolved CSS colour tokens for charts (recharts needs concrete values). */
export function useChartColors() {
  const { theme } = useTheme();
  return useMemo(() => {
    const css = getComputedStyle(document.documentElement);
    const read = (name: string) => css.getPropertyValue(name).trim();
    return {
      series: read('--chart-1'), grid: read('--chart-grid'), axis: read('--chart-axis'), surface: read('--surface'),
      fg: read('--fg'), border: read('--border'), up: read('--up'), down: read('--down'), theme,
    };
  }, [theme]);
}
