/**
 * Site-drawn menu in place of the browser's select, on the same grammar as the
 * Scryglass Menu: a bordered trigger showing the current value, a listbox
 * popover, arrow keys to move, Enter or Space to choose, Escape or an outside
 * click to close. It only ever shows values the caller offers; a value the
 * options do not contain renders the placeholder so a stale choice stays
 * visible instead of silently snapping to something else.
 */
import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "./Icon";

export type MenuOption = { value: string; label: string; disabled?: boolean };

type MenuProps = {
  value: string;
  options: MenuOption[];
  onChange: (value: string) => void;
  /** Accessible name for the trigger and the list. */
  "aria-label": string;
  /** Shown when `value` matches none of the options. */
  placeholder?: string;
  disabled?: boolean;
  className?: string;
};

export function Menu({
  value,
  options,
  onChange,
  "aria-label": ariaLabel,
  placeholder = "Choose",
  disabled,
  className,
}: MenuProps) {
  const [open, setOpen] = useState(false);
  const selectedIndex = options.findIndex((option) => option.value === value);
  const [active, setActive] = useState(Math.max(0, selectedIndex));
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();
  const current = selectedIndex >= 0 ? options[selectedIndex] : null;

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    list.current
      ?.querySelector<HTMLElement>(`[data-index="${active}"]`)
      ?.focus();
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, active]);

  const focusIndex = (index: number) => {
    setActive(index);
    list.current
      ?.querySelector<HTMLElement>(`[data-index="${index}"]`)
      ?.focus();
  };
  const choose = (option: MenuOption) => {
    if (option.disabled) return;
    onChange(option.value);
    setOpen(false);
    trigger.current?.focus();
  };
  const move = (delta: number) =>
    focusIndex((active + delta + options.length) % options.length);

  return (
    <div
      className={["calculator-menu", className].filter(Boolean).join(" ")}
      ref={root}
    >
      <button
        ref={trigger}
        type="button"
        className="calculator-menu-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => {
          setActive(Math.max(0, selectedIndex));
          setOpen((state) => !state);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className={current ? undefined : "calculator-menu-placeholder"}>
          {current?.label ?? placeholder}
        </span>
        <Icon name="chevron" size={14} className="calculator-menu-chevron" />
      </button>
      {open && (
        <ul
          id={id}
          ref={list}
          role="listbox"
          aria-label={ariaLabel}
          className="calculator-menu-list"
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              move(1);
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              move(-1);
            }
            if (event.key === "Home") {
              event.preventDefault();
              focusIndex(0);
            }
            if (event.key === "End") {
              event.preventDefault();
              focusIndex(options.length - 1);
            }
          }}
        >
          {options.map((option, index) => {
            const selected = option.value === value;
            return (
              <li
                key={option.value}
                role="option"
                aria-selected={selected}
                aria-disabled={option.disabled || undefined}
                data-index={index}
                tabIndex={index === active ? 0 : -1}
                className="calculator-menu-option"
                onClick={() => choose(option)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    choose(option);
                  }
                }}
                onMouseEnter={() => setActive(index)}
              >
                <span>{option.label}</span>
                {selected && <Icon name="pick" size={14} />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
