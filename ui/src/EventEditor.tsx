import type { Champion } from "./types";
import type { AuthoredEvent } from "./scenario-state";
import { Icon } from "./Icon";
import { Menu } from "./Menu";
export interface EventActor {
  id: string;
  label: string;
  team: string;
  champion?: Champion;
  ranks: Record<string, number>;
}
export type EventCapabilities = Record<
  string,
  Record<string, { recipients: string[]; reach?: string }>
>;
export function EventEditor({
  enabled,
  onEnabled,
  events,
  onChange,
  actors,
  duration,
  capabilities,
}: {
  enabled: boolean;
  onEnabled: (value: boolean) => void;
  events: AuthoredEvent[];
  onChange: (events: AuthoredEvent[]) => void;
  actors: EventActor[];
  duration: number;
  capabilities: EventCapabilities;
}) {
  const casters = actors.filter(
    (actor) => actor.champion && capabilities[actor.champion.name],
  );
  const slots = (actor: EventActor | undefined) =>
    Object.keys(
      capabilities[actor?.champion?.name ?? ""] ?? {},
    ) as AuthoredEvent["slot"][];
  function recipients(actor: EventActor | undefined, slot: string) {
    const allowed =
      capabilities[actor?.champion?.name ?? ""]?.[slot]?.recipients ?? [];
    return actors.filter((target) =>
      allowed.includes(
        target.id === actor?.id
          ? "self"
          : target.team === actor?.team
            ? "ally"
            : "enemy",
      ),
    );
  }
  function edit(id: string, change: Partial<AuthoredEvent>) {
    onChange(
      events.map((event) => {
        if (event.id !== id) return event;
        const next = { ...event, ...change };
        const actor = actors.find((actor) => actor.id === next.caster_id);
        if (change.caster_id && !slots(actor).includes(next.slot))
          next.slot = slots(actor)[0] ?? "Q";
        if (change.caster_id || change.slot) {
          const targets = recipients(actor, next.slot);
          if (!targets.some((target) => target.id === next.recipient_id))
            next.recipient_id = targets[0]?.id ?? "";
        }
        return next;
      }),
    );
  }
  function add() {
    const actor = casters[0];
    if (!actor) return;
    const slot =
      slots(actor).find((key) => (actor.ranks[key] ?? 0) > 0) ??
      slots(actor)[0];
    const targets = recipients(actor, slot);
    onChange([
      ...events,
      {
        id: crypto.randomUUID(),
        time: 0,
        caster_id: actor.id,
        slot,
        recipient_id: targets[0]?.id ?? "",
      },
    ]);
  }
  return (
    <section className="calculator-event-editor" aria-label="Targeted casts">
      <div className="calculator-section-heading">
        <div>
          <h2>Targeted casts</h2>
          <p>Set the time, caster, and recipient for each spell.</p>
        </div>
        <label className="calculator-check">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => onEnabled(e.target.checked)}
          />
          Use targeted casts
        </label>
      </div>
      {enabled ? (
        <>
          <div
            className="calculator-event-table-wrap"
            tabIndex={0}
            role="region"
            aria-label="Spell sequence, scroll to view all columns"
          >
            <table className="calculator-event-table">
              <caption className="calculator-sr-only">
                Authored spell events
              </caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Caster</th>
                  <th scope="col">Spell</th>
                  <th scope="col">Recipient</th>
                  <th scope="col">
                    <span className="calculator-sr-only">Remove event</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {events.map((event, index) => {
                  const actor = actors.find(
                    (candidate) => candidate.id === event.caster_id,
                  );
                  const available = slots(actor);
                  const targets = recipients(actor, event.slot);
                  return (
                    <tr key={event.id}>
                      <td>
                        <label>
                          <span className="calculator-sr-only">
                            Event {index + 1} time in seconds
                          </span>
                          <input
                            type="number"
                            min={0}
                            max={duration}
                            step={0.1}
                            value={event.time}
                            onChange={(e) =>
                              edit(event.id, { time: Number(e.target.value) })
                            }
                          />
                          <span>s</span>
                        </label>
                      </td>
                      <td>
                        <Menu
                          aria-label={`Event ${index + 1} caster`}
                          value={event.caster_id}
                          placeholder="Choose supported caster"
                          options={casters.map((candidate) => ({
                            value: candidate.id,
                            label: candidate.label,
                          }))}
                          onChange={(caster_id) =>
                            edit(event.id, { caster_id })
                          }
                        />
                      </td>
                      <td>
                        <Menu
                          aria-label={`Event ${index + 1} spell`}
                          value={event.slot}
                          placeholder="Choose supported spell"
                          options={available.map((slot) => ({
                            value: slot,
                            label: `${slot} · ${
                              actor?.champion?.abilities[slot]?.name ?? slot
                            }${
                              capabilities[actor?.champion?.name ?? ""]?.[slot]
                                ?.reach === "every_enemy"
                                ? " (every enemy)"
                                : ""
                            }${!actor?.ranks[slot] ? " (unlearned)" : ""}`,
                          }))}
                          onChange={(slot) =>
                            edit(event.id, {
                              slot: slot as AuthoredEvent["slot"],
                            })
                          }
                        />
                      </td>
                      <td>
                        <Menu
                          aria-label={`Event ${index + 1} recipient`}
                          value={event.recipient_id}
                          placeholder="Choose a legal recipient"
                          options={targets.map((candidate) => ({
                            value: candidate.id,
                            label: `${candidate.label}${
                              candidate.id === event.caster_id ? " (self)" : ""
                            }`,
                          }))}
                          onChange={(recipient_id) =>
                            edit(event.id, { recipient_id })
                          }
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          aria-label={`Remove event ${index + 1}`}
                          onClick={() =>
                            onChange(
                              events.filter((row) => row.id !== event.id),
                            )
                          }
                        >
                          <Icon name="close" leading />
                          Remove
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!events.length && (
            <p className="calculator-event-empty">
              Add a spell event to start a sequence for its caster.
            </p>
          )}
          <button
            type="button"
            className="calculator-secondary"
            disabled={!casters.length || events.length >= 100}
            onClick={add}
          >
            <Icon name="plus" leading />
            Add spell event
          </button>
          <p className="calculator-event-help">
            Listed casters use only their authored spells. Other champions keep
            their learned-spell schedule. The engine checks resources,
            cooldowns, and legal recipients.
          </p>
        </>
      ) : (
        <p className="calculator-event-help">
          The engine schedules learned spells within the fight window. Turn on
          targeted casts to direct individual spells.
        </p>
      )}
      <details className="calculator-event-capabilities">
        <summary>Available spell controls</summary>
        <p>
          {Object.entries(capabilities)
            .map(
              ([champion, abilities]) =>
                `${champion} ${Object.keys(abilities).join(" / ")}`,
            )
            .join(" · ") || "Loading the engine’s supported cast controls…"}
        </p>
        <p>
          Other spells keep their calculated schedule. More controls require
          verified timing and target rules.
        </p>
        <p>
          Resource costs use the planned spell schedule. A spell blocked by
          death or crowd control can still consume planned mana, which can
          affect later casts.
        </p>
      </details>
    </section>
  );
}
