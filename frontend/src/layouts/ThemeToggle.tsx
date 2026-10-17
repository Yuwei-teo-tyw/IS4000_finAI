import { Moon, Sun } from "lucide-react";
import { useTheme } from "./useTheme";

export default function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  const label = dark ? "Switch To Light Mode" : "Switch To Dark Mode";
  return (
    <button type="button" onClick={toggle} aria-label={label} title={label}
      className="flex min-h-10 w-full items-center gap-3 rounded-sm border border-hairline px-3 text-[13.5px] text-ink hover:bg-surface-300 max-md:justify-center max-md:px-0">
      {dark ? <Sun size={16} strokeWidth={1.5} aria-hidden /> : <Moon size={16} strokeWidth={1.5} aria-hidden />}
      <span className="max-md:sr-only">{dark ? "Light Mode" : "Dark Mode"}</span>
    </button>
  );
}
