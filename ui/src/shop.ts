import type { Item } from "./types.ts";

export function shopGroup(item: Pick<Item, "rank">): string {
  if (item.rank?.includes("LEGENDARY")) return "Legendary";
  if (item.rank?.includes("EPIC")) return "Epic";
  if (item.rank?.some((rank) => ["STARTER", "BASIC"].includes(rank)))
    return "Starter & Basic";
  return "Other items";
}

/** Convert source markup into plain React text while retaining numerical branches. */
export function wikiText(raw: string): string {
  const variables = new Map<string, string>();
  let text = raw;
  for (let pass = 0; pass < 32 && /\{\{[^{}]*\}\}/.test(text); pass++) {
    text = text.replace(/\{\{([^{}]*)\}\}/g, (_, body: string) => {
      const parts = body.split("|").map((part) => part.trim());
      const name = (parts.shift() ?? "").toLowerCase();
      const named = new Map(
        parts
          .filter((part) => /^[\w ]+\s*=/.test(part))
          .map((part) => {
            const at = part.indexOf("=");
            return [
              part.slice(0, at).trim().toLowerCase(),
              part.slice(at + 1).trim(),
            ];
          }),
      );
      const values = parts.filter((part) => !/^[\w ]+\s*=/.test(part));
      const first = values[0] ?? "";
      if (name.startsWith("#vardefineecho:")) {
        variables.set(name.slice(15), first);
        return first;
      }
      if (name.startsWith("#var:")) return variables.get(name.slice(5)) ?? "";
      if (name === "degree") return "°";
      if (name === "g") return `${first} gold`;
      if (name === "rd")
        return values.length > 1
          ? `${first} melee / ${values[1]} ranged`
          : first;
      if (name === "pp") {
        const context = named.get("formula") ?? named.get("type");
        return context ? `${first} (${context})` : values.join("; ");
      }
      if (name === "tt" || name === "ft")
        return values[1] ? `${first} (${values[1]})` : first;
      if (name === "tip" && named.get("icononly") === "true") return "";
      if (["tip", "sti", "stil", "ui"].includes(name))
        return values[1] ?? first;
      if (
        ["as", "ap", "fd", "nie", "sbc", "ii", "si", "bi", "rutngt"].includes(
          name,
        )
      )
        return first;
      return values.length ? values.join(" / ") : name;
    });
  }
  return text
    .replace(/\[\[(?:File|Image):[^\]]*\]\]/gi, "")
    .replace(/\[\[([^\]|]*)\|([^\]]*)\]\]/g, "$2")
    .replace(/\[\[([^\]]*)\]\]/g, "$1")
    .replace(/<br\s*\/?\s*>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/'{2,3}/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/[ \t]+/g, " ")
    .trim();
}
