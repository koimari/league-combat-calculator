/**
 * Calculator icons, a subset of the Scryglass set drawn on the same geometry:
 * 24-unit grid, 2-unit safe area, 1.5 stroke, round caps and joins, currentColor.
 * Keep glyphs byte-identical with apps/scryglass/src/components/Icon.tsx in
 * koimari/scryglass so the two surfaces read as one product.
 */
import { createElement, type SVGProps } from "react";

type Shape = ["path" | "circle" | "rect" | "ellipse", Record<string, string>];

const GLYPHS = {
  lens: [
    ["circle", { cx: "10.5", cy: "10.5", r: "6.5" }],
    ["path", { d: "m15.5 15.5 5 5" }],
  ],
  ratings: [["path", { d: "M6 20v-6M12 20V6M18 20v-9M3.5 20h17" }]],
  folio: [
    ["rect", { x: "7.5", y: "3.5", width: "13", height: "13", rx: "1.5" }],
    ["path", { d: "M3.5 7.5v10a3 3 0 0 0 3 3h10" }],
  ],
  clear: [
    ["circle", { cx: "12", cy: "12", r: "8.5" }],
    ["path", { d: "m9 9 6 6M15 9l-6 6" }],
  ],
  refresh: [["path", { d: "M20.5 12A8.5 8.5 0 1 1 19.5 8M20.5 3.5V8h-4.5" }]],
  history: [
    ["path", { d: "M3.5 12A8.5 8.5 0 1 0 4.5 8M3.5 3.5V8H8M12 7.5V12l3 2" }],
  ],
  download: [["path", { d: "M12 3.5V15M7.5 10.5 12 15l4.5-4.5M3.5 20.5h17" }]],
  copy: [
    ["rect", { x: "8.5", y: "8.5", width: "12", height: "12", rx: "1.5" }],
    [
      "path",
      {
        d: "M15.5 8.5V5A1.5 1.5 0 0 0 14 3.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h3.5",
      },
    ],
  ],
  close: [["path", { d: "m6 6 12 12M18 6 6 18" }]],
  info: [
    ["circle", { cx: "12", cy: "12", r: "8.5" }],
    ["path", { d: "M12 11v5M12 8h.01" }],
  ],
  "zoom-in": [
    ["circle", { cx: "10.5", cy: "10.5", r: "6.5" }],
    ["path", { d: "m15.5 15.5 5 5M10.5 7.5v6M7.5 10.5h6" }],
  ],
  pick: [
    ["circle", { cx: "12", cy: "12", r: "8.5" }],
    ["path", { d: "m8 12.5 2.5 2.5 5.5-6" }],
  ],
  sort: [
    [
      "path",
      { d: "M8 4.5v15M4.5 16 8 19.5 11.5 16M16 19.5v-15M12.5 8 16 4.5 19.5 8" },
    ],
  ],
  "arrow-down": [["path", { d: "M12 4.5v15M6.5 14 12 19.5 17.5 14" }]],
  plus: [["path", { d: "M12 5v14M5 12h14" }]],
  "arrow-right": [["path", { d: "M4.5 12h15M14 6.5l5.5 5.5-5.5 5.5" }]],
  "arrow-left": [["path", { d: "M19.5 12h-15M10 6.5 4.5 12l5.5 5.5" }]],
  chevron: [["path", { d: "m6.5 9.5 5.5 5.5 5.5-5.5" }]],
} satisfies Record<string, Shape[]>;

export type IconName = keyof typeof GLYPHS;

type IconProps = Omit<SVGProps<SVGSVGElement>, "name"> & {
  name: IconName;
  size?: number;
  label?: string;
  leading?: boolean;
};

/** Decorative by default; pass `label` when the icon is the only content of a control. `leading` spaces it from a following label. */
export function Icon({
  name,
  size = 16,
  label,
  leading,
  className,
  style,
  ...rest
}: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      className={className}
      style={{
        verticalAlign: "-0.22em",
        flexShrink: 0,
        marginRight: leading ? "0.4rem" : undefined,
        ...style,
      }}
      {...rest}
    >
      {GLYPHS[name].map(([tag, attrs], index) =>
        createElement(tag, { key: index, ...attrs }),
      )}
    </svg>
  );
}
