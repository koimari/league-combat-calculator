import { createRoot } from "react-dom/client";
import { Calculator } from "./Calculator";
import "./calculator.css";
import "./standalone.css";
const mount = document.getElementById("calculator-app");
if (mount) createRoot(mount).render(<Calculator advancedHref="/advanced" />);
const theme = document.getElementById(
  "calculator-theme",
) as HTMLSelectElement | null;
try {
  const saved = localStorage.getItem("calculator-theme");
  if (
    saved &&
    [
      "paper",
      "midnight",
      "terminal",
      "amber",
      "groovebox",
      "cobalt",
      "rosewater",
      "moss",
      "ultraviolet",
      "monochrome",
    ].includes(saved)
  ) {
    document.body.dataset.theme = saved;
    if (theme) theme.value = saved;
  }
} catch {}
theme?.addEventListener("change", () => {
  document.body.dataset.theme = theme.value;
  try {
    localStorage.setItem("calculator-theme", theme.value);
  } catch {}
});
