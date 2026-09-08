"use client";

import {
  Children,
  cloneElement,
  createElement,
  isValidElement,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import "./tooltip.css";

export interface GameTooltipProps {
  children: ReactNode;
  title: string;
  description: string;
  meta?: string;
  className?: string;
}
const coloredTags: Record<string, string> = {
  scalead: "ad",
  physicaldamage: "ad",
  scaleap: "ap",
  magicdamage: "ap",
  truedamage: "true",
  scalehealth: "health",
  healing: "health",
  heal: "health",
  scalemana: "mana",
  mana: "mana",
  gold: "gold",
  scalelevel: "level",
  speed: "speed",
  attention: "emphasis",
  statgood: "health",
  keywordmajor: "emphasis",
};
function decodeText(text: string): string {
  return text.replace(
    /&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi,
    (whole, entity: string) => {
      if (entity.startsWith("#")) {
        const point =
          entity[1].toLowerCase() === "x"
            ? parseInt(entity.slice(2), 16)
            : parseInt(entity.slice(1), 10);
        return point > 0 && point <= 0x10ffff
          ? String.fromCodePoint(point)
          : whole;
      }
      return (
        (
          {
            amp: "&",
            lt: "<",
            gt: ">",
            quot: '"',
            apos: "'",
            nbsp: " ",
          } as Record<string, string>
        )[entity.toLowerCase()] ?? whole
      );
    },
  );
}
/** Render a small source-text vocabulary as React nodes. Source attributes are never applied. */
export function TooltipDescription({ text }: { text: string }) {
  const stack: { tag: string; nodes: ReactNode[] }[] = [
    { tag: "root", nodes: [] },
  ];
  let key = 0;
  const close = () => {
    const current = stack.pop();
    if (!current || !stack.length) return;
    const htmlTag = ["b", "strong"].includes(current.tag)
      ? "strong"
      : ["i", "em"].includes(current.tag)
        ? "em"
        : current.tag === "li"
          ? "li"
          : ["ul", "ol"].includes(current.tag)
            ? current.tag
            : "span";
    stack[stack.length - 1].nodes.push(
      createElement(
        htmlTag,
        {
          key: key++,
          className: coloredTags[current.tag]
            ? `game-tooltip-value game-tooltip-value-${coloredTags[current.tag]}`
            : undefined,
        },
        current.nodes,
      ),
    );
  };
  for (const token of text.split(/(<[^>]*>)/g)) {
    if (!token) continue;
    if (!token.startsWith("<")) {
      stack[stack.length - 1].nodes.push(decodeText(token));
      continue;
    }
    const tag = token.match(/^<\s*(\/?)\s*([\w-]+)/);
    if (!tag) {
      stack[stack.length - 1].nodes.push(token);
      continue;
    }
    const name = tag[2].toLowerCase();
    if (name === "br" || name === "hr") {
      stack[stack.length - 1].nodes.push(createElement(name, { key: key++ }));
      continue;
    }
    if (tag[1]) {
      const index = stack.map((entry) => entry.tag).lastIndexOf(name);
      if (index > 0) while (stack.length > index) close();
    } else if (
      !/\/\s*>$/.test(token) &&
      !["img", "input", "meta", "link"].includes(name)
    ) {
      stack.push({ tag: name, nodes: [] });
    }
  }
  while (stack.length > 1) close();
  return <>{stack[0].nodes}</>;
}

export function GameTooltip({
  children,
  title,
  description,
  meta,
  className = "",
}: GameTooltipProps) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [portalRoot, setPortalRoot] = useState<HTMLElement | null>(null);
  const anchor = useRef<HTMLSpanElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const id = useId();
  const closeTimer = useRef<number | undefined>(undefined);
  const cancelClose = () => {
    window.clearTimeout(closeTimer.current);
    closeTimer.current = undefined;
  };
  const show = () => {
    cancelClose();
    setPortalRoot(anchor.current?.closest("dialog") ?? document.body);
    document.dispatchEvent(
      new CustomEvent("game-tooltip-open", { detail: id }),
    );
    setOpen(true);
  };
  const scheduleClose = () => {
    if (!pinned) {
      cancelClose();
      closeTimer.current = window.setTimeout(() => setOpen(false), 150);
    }
  };
  const close = () => {
    cancelClose();
    setOpen(false);
    setPinned(false);
  };
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const source = anchor.current?.getBoundingClientRect();
      const tooltip = popup.current;
      if (!source || !tooltip) return;
      const size = tooltip.getBoundingClientRect();
      const gap = 12;
      const width = document.documentElement.clientWidth;
      const height = window.innerHeight;
      const left = Math.max(
        gap,
        Math.min(
          source.left + source.width / 2 - size.width / 2,
          width - size.width - gap,
        ),
      );
      const above = source.top - size.height - gap;
      const below = source.bottom + gap;
      const top =
        above >= gap
          ? above
          : below + size.height <= height - gap
            ? below
            : Math.max(gap, height - size.height - gap);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
      tooltip.style.visibility = "visible";
    };
    place();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        setOpen(false);
        setPinned(false);
      }
    };
    const outside = (event: PointerEvent) => {
      if (
        pinned &&
        !anchor.current?.contains(event.target as Node) &&
        !popup.current?.contains(event.target as Node)
      ) {
        setOpen(false);
        setPinned(false);
      }
    };
    const openedElsewhere = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== id) {
        setOpen(false);
        setPinned(false);
      }
    };
    document.addEventListener("game-tooltip-open", openedElsewhere);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("keydown", escape, true);
    document.addEventListener("pointerdown", outside);
    return () => {
      window.clearTimeout(closeTimer.current);
      document.removeEventListener("game-tooltip-open", openedElsewhere);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("keydown", escape, true);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open, pinned, title, description, meta, id]);
  const content = Children.map(children, (child) => {
    if (!isValidElement<Record<string, unknown>>(child)) return child;
    const describedBy = [child.props["aria-describedby"], open ? id : undefined]
      .filter(Boolean)
      .join(" ");
    return cloneElement(child, {
      "aria-describedby": describedBy || undefined,
    });
  });
  return (
    <span
      className={`game-tooltip-anchor ${className}`}
      ref={anchor}
      onPointerEnter={(event) => {
        if (event.pointerType !== "touch") show();
      }}
      onPointerLeave={scheduleClose}
      onFocusCapture={show}
      onBlurCapture={(event) => {
        if (!pinned && !event.currentTarget.contains(event.relatedTarget))
          scheduleClose();
      }}
    >
      {content}
      <button
        type="button"
        className="game-tooltip-info"
        aria-label={`Show details for ${title}`}
        aria-expanded={open && pinned}
        aria-controls={open ? id : undefined}
        onClick={(event) => {
          event.stopPropagation();
          if (pinned) close();
          else {
            setPinned(true);
            show();
          }
        }}
      >
        i
      </button>
      {open &&
        portalRoot &&
        createPortal(
          <div
            ref={popup}
            id={id}
            role="tooltip"
            className={`game-tooltip-popup ${pinned ? "game-tooltip-pinned" : ""}`}
            style={{ visibility: "hidden" }}
            onPointerEnter={cancelClose}
            onPointerLeave={scheduleClose}
            onFocusCapture={cancelClose}
          >
            <header>
              <strong>{title}</strong>
              {pinned && (
                <button
                  type="button"
                  aria-label="Close details"
                  onClick={close}
                >
                  ×
                </button>
              )}
            </header>
            {description && (
              <div className="game-tooltip-description">
                <TooltipDescription text={description} />
              </div>
            )}
            {meta && <div className="game-tooltip-meta">{meta}</div>}
          </div>,
          portalRoot,
        )}
    </span>
  );
}
export default GameTooltip;
