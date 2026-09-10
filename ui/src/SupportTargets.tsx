import type { Result } from "./types";
const scopes = new Set([
  "one_teammate",
  "self_and_one_teammate",
  "explicit_selected_ally",
  "healed_or_shielded_ally",
  "most_wounded_ally",
  "nearest_most_wounded_ally",
  "other_nearest_wounded_ally",
]);
export interface SupportOwner {
  id: string;
  runtimeId: string;
  name: string;
  team: string;
  selections: Record<string, number>;
}
export function SupportTargets({
  result,
  actors,
  onChange,
}: {
  result: Result;
  actors: SupportOwner[];
  onChange: (id: string, key: string, value: number) => void;
}) {
  const combat = result.combat as
    | { support_events?: Record<string, unknown>[] }
    | undefined;
  const packets = new Map<string, Record<string, unknown>>();
  for (const event of combat?.support_events ?? []) {
    if (
      typeof event.target_selection_key === "string" &&
      typeof event.attacker === "string" &&
      scopes.has(String(event.target_scope)) &&
      event.target !== event.attacker
    )
      packets.set(`${event.attacker}:${event.target_selection_key}`, event);
  }
  const controls = [...packets.values()].flatMap((event) => {
    const owner = actors.find((actor) => actor.runtimeId === event.attacker);
    if (!owner) return [];
    const teammates = actors.filter(
      (actor) => actor.team === owner.team && actor.id !== owner.id,
    );
    if (!teammates.length) return [];
    const key = String(event.target_selection_key);
    return [
      {
        owner,
        teammates,
        key,
        label: `${owner.name} · ${String(event.source ?? event.kind ?? "Support effect")}`,
      },
    ];
  });
  if (!controls.length) return null;
  return (
    <section
      className="calculator-support-targets"
      aria-label="Default support recipients"
    >
      <h3>Default support recipients</h3>
      <p>
        These choices apply to each occurrence in the calculated sequence. Use
        an authored sequence to target individual casts.
      </p>
      <div className="calculator-options">
        {controls.map(({ owner, teammates, key, label }) => (
          <label className="calculator-field" key={`${owner.id}:${key}`}>
            <span>{label}</span>
            <select
              aria-label={`Recipient for ${label}`}
              value={Math.min(owner.selections[key] ?? 0, teammates.length - 1)}
              onChange={(event) =>
                onChange(owner.id, key, Number(event.target.value))
              }
            >
              {teammates.map((actor, index) => (
                <option key={actor.id} value={index}>
                  {actor.name}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
    </section>
  );
}
