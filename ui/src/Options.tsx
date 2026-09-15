import type { Option, Values } from "./types";
import { Menu } from "./Menu";

const label = (value: string) => value.replaceAll("_", " ");

export function Options({
  options,
  values,
  onChange,
}: {
  options: Option[];
  values: Values;
  onChange: (values: Values) => void;
}) {
  return (
    <div className="calculator-options">
      {options.map((option) => {
        const value = values[option.key] ?? option.default ?? "";
        const type =
          option.type ?? (option.kind === "switch" ? "switch" : "int");
        const change = (next: Values[string]) =>
          onChange({ ...values, [option.key]: next });
        const choices = option.options ?? option.choices;
        return (
          <label
            className={
              type === "bool" || type === "switch"
                ? "calculator-check"
                : "calculator-field"
            }
            key={option.key}
          >
            {type === "bool" || type === "switch" ? (
              <>
                <input
                  type="checkbox"
                  checked={Boolean(value)}
                  onChange={(e) =>
                    change(
                      type === "switch"
                        ? Number(e.target.checked)
                        : e.target.checked,
                    )
                  }
                />
                <span>{option.label ?? label(option.key)}</span>
              </>
            ) : (
              <>
                <span>{option.label ?? label(option.key)}</span>
                {choices ? (
                  <Menu
                    aria-label={option.label ?? label(option.key)}
                    value={String(value)}
                    options={choices.map((choice) =>
                      typeof choice === "string"
                        ? { value: choice, label: choice }
                        : { value: String(choice.value), label: choice.label },
                    )}
                    onChange={change}
                  />
                ) : type === "string_list" ? (
                  <input
                    value={
                      Array.isArray(value) ? value.join(", ") : String(value)
                    }
                    placeholder="Separate values with commas"
                    onChange={(e) =>
                      change(
                        e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      )
                    }
                  />
                ) : (
                  <input
                    type={
                      ["int", "float", "number"].includes(type)
                        ? "number"
                        : "text"
                    }
                    min={option.min ?? option.minimum}
                    max={option.max ?? option.maximum}
                    step={option.step ?? (type === "int" ? 1 : "any")}
                    value={String(value)}
                    onChange={(e) =>
                      change(
                        e.target.type === "number"
                          ? e.target.value === ""
                            ? ""
                            : Number(e.target.value)
                          : e.target.value,
                      )
                    }
                  />
                )}
              </>
            )}
          </label>
        );
      })}
    </div>
  );
}
