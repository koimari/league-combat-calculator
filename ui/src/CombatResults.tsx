import { useId, useState, type ReactNode } from "react";
import type { Result } from "./types";
import "./combat-results.css";
type Row = Record<string, unknown>;
const record = (v: unknown): Row =>
  v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Row) : {};
const rows = (v: unknown): Row[] =>
  Array.isArray(v)
    ? v.filter((x) => x !== null && typeof x === "object" && !Array.isArray(x))
    : [];
const text = (v: unknown, fallback = "Not reported") =>
  typeof v === "string" && v ? v : fallback;
const number = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;
const amount = (v: unknown) =>
  number(v)?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? "—";
function status(s: Row) {
  if (s.revived === true && s.terminal_phase === "revived")
    return `Revived${number(s.revive_time) === null ? "" : ` at ${amount(s.revive_time)}s`}`;
  if (s.survived_window === true) return "Alive at window end";
  if (number(s.death_time) !== null)
    return `Defeated at ${amount(s.death_time)}s`;
  return text(s.terminal_phase, "Survival not reported").replaceAll("_", " ");
}
function Ledger({
  title,
  events,
  damage,
  labels,
  read,
  path,
}: {
  title: string;
  events: Row[];
  damage?: boolean;
  labels: Map<string, string>;
  read: (value: unknown, path: string) => ReactNode;
  path: string;
}) {
  const [limit, setLimit] = useState(50);
  const label = (v: unknown) =>
    typeof v === "string" ? (labels.get(v) ?? v) : "Not reported";
  return (
    <details className="combat-ledger">
      <summary>
        {title}
        <span>{events.length} events</span>
      </summary>
      {!events.length ? (
        <p>No events were returned.</p>
      ) : (
        <>
          <div
            className="combat-table-scroll"
            tabIndex={0}
            role="region"
            aria-label={`${title}, scroll to view all columns`}
          >
            <table>
              <caption>{title} in the order returned by the engine</caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Source and participants</th>
                  <th scope="col">
                    {damage ? "Applied damage" : "Applied amount"}
                  </th>
                  <th scope="col">Raw amount</th>
                  <th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {events.slice(0, limit).map((event, index) => (
                  <tr key={index}>
                    <td>
                      {number(event.time) === null ? (
                        "—"
                      ) : (
                        <>{read(event.time, `${path}[${index}].time`)}s</>
                      )}
                    </td>
                    <td>
                      <strong>{text(event.source)}</strong>
                      <small>
                        {label(event.attacker)}
                        {event.target !== undefined ||
                        event.recipient !== undefined
                          ? ` → ${label(event.target ?? event.recipient)}`
                          : ""}
                      </small>
                      <small>
                        {text(event.damage_type ?? event.kind, "")}
                        {typeof event.skipped_reason === "string"
                          ? ` · ${event.skipped_reason.replaceAll("_", " ")}`
                          : ""}
                        {typeof event.event_precision === "string"
                          ? ` · ${event.event_precision}`
                          : ""}
                      </small>
                    </td>
                    <td>
                      {read(
                        damage ? event.damage : event.applied_amount,
                        `${path}[${index}].${damage ? "damage" : "applied_amount"}`,
                      )}
                    </td>
                    <td>
                      {read(
                        damage ? event.raw_damage : event.raw_amount,
                        `${path}[${index}].${damage ? "raw_damage" : "raw_amount"}`,
                      )}
                    </td>
                    <td>
                      <details className="combat-source-details">
                        <summary>Full event details</summary>
                        <dl>
                          {Object.entries(event).map(([key, value]) => (
                            <div key={key}>
                              <dt>{key.replaceAll("_", " ")}</dt>
                              <dd>
                                {typeof value === "number"
                                  ? read(value, `${path}[${index}].${key}`)
                                  : typeof value === "string"
                                    ? value
                                    : value === null
                                      ? "Not reported"
                                      : JSON.stringify(value)}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {limit < events.length && (
            <button
              type="button"
              className="combat-show-more"
              onClick={() => setLimit((value) => value + 50)}
            >
              Show next {Math.min(50, events.length - limit)} events
            </button>
          )}
        </>
      )}
    </details>
  );
}
/** Display the published receipt without recalculating outcomes. */
export function CombatResults({
  result,
  title,
}: {
  result: Result;
  title: string;
}) {
  const id = useId();
  const combat = record(result.combat);
  if (!Object.keys(combat).length) return null;
  const dispositions = record(combat.dispositions);
  const withheld = (path: string) =>
    record(dispositions[path]).disposition === "WITHHELD";
  const read = (value: unknown, path: string): ReactNode => {
    const disposition = record(dispositions[path]);
    if (disposition.disposition === "WITHHELD")
      return (
        <span
          title={text(
            disposition.reason ?? disposition.note,
            "The engine withheld this value.",
          )}
        >
          Withheld
        </span>
      );
    return amount(value);
  };
  const participants = rows(combat.participants),
    breakdown = rows(combat.breakdown),
    objective = record(combat.objective);
  const labels = new Map(
    participants.map((p) => [
      text(p.participant_id, ""),
      `${text(p.champion)} · ${text(p.team)}`,
    ]),
  );
  const fields = [
    ["Main team damage before defeat", "main_team_damage_before_death"],
    ["Enemy team damage before defeat", "enemy_team_damage_before_death"],
    ["Main team survivors", "surviving_main_team"],
    ["Main team effective health", "main_team_effective_health"],
    ["Enemy team effective health", "enemy_team_effective_health"],
  ];
  return (
    <section className="combat-results" aria-labelledby={`${id}-title`}>
      <header>
        <h3 id={`${id}-title`}>{title}</h3>
        {number(combat.duration) !== null && (
          <p>{amount(combat.duration)} second combat window</p>
        )}
      </header>
      {record(combat.timeline_coverage).complete === false && (
        <p className="calculator-notice">
          Event coverage is incomplete. Read the receipt limits before comparing
          these values.
        </p>
      )}
      <dl className="combat-team-outcomes">
        {fields
          .filter(
            ([, key]) =>
              number(objective[key]) !== null || withheld(`objective.${key}`),
          )
          .map(([label, key]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{read(objective[key], `objective.${key}`)}</dd>
            </div>
          ))}
      </dl>
      <div
        className="combat-table-scroll"
        tabIndex={0}
        role="region"
        aria-label={`${title} participant survival, scroll to view all columns`}
      >
        <table>
          <caption>Participant health and survival</caption>
          <thead>
            <tr>
              <th scope="col">Participant</th>
              <th scope="col">Outcome</th>
              <th scope="col">Health at end</th>
              <th scope="col">Damage dealt</th>
              <th scope="col">Health damage taken</th>
              <th scope="col">Shield absorbed</th>
              <th scope="col">Healing received</th>
            </tr>
          </thead>
          <tbody>
            {participants.map((p, index) => {
              const s = record(p.survival),
                output = breakdown.find(
                  (row) => row.participant_id === p.participant_id,
                ),
                hp = withheld(`participants[${index}].survival.ending_health`)
                  ? null
                  : number(s.ending_health),
                max = withheld(`participants[${index}].survival.max_health`)
                  ? null
                  : number(s.max_health);
              return (
                <tr key={text(p.participant_id, String(index))}>
                  <th scope="row">
                    <strong>{text(p.champion)}</strong>
                    <small>
                      {text(p.team)} · {text(p.participant_id)}
                      {number(p.level) === null
                        ? ""
                        : ` · Level ${amount(p.level)}`}
                    </small>
                  </th>
                  <td>
                    {withheld(`participants[${index}].survival.death_time`)
                      ? "Survival withheld"
                      : status(s)}
                  </td>
                  <td>
                    {read(
                      s.ending_health,
                      `participants[${index}].survival.ending_health`,
                    )}{" "}
                    /{" "}
                    {read(
                      s.max_health,
                      `participants[${index}].survival.max_health`,
                    )}
                    {hp !== null && max !== null && max > 0 && (
                      <meter
                        min={0}
                        max={max}
                        value={Math.max(0, Math.min(max, hp))}
                        aria-label={`${text(p.champion)} health at window end`}
                      />
                    )}
                  </td>
                  <td>
                    {read(
                      output?.total_damage,
                      `breakdown[${breakdown.indexOf(output!)}].total_damage`,
                    )}
                  </td>
                  <td>
                    {read(
                      s.health_damage,
                      `participants[${index}].survival.health_damage`,
                    )}
                  </td>
                  <td>
                    {read(
                      s.shield_absorbed,
                      `participants[${index}].survival.shield_absorbed`,
                    )}
                  </td>
                  <td>
                    {read(
                      s.healing_received,
                      `participants[${index}].survival.healing_received`,
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!participants.length && (
          <p>No participant survival rows were returned.</p>
        )}
      </div>
      <Ledger
        title="Damage timeline"
        events={rows(combat.events)}
        damage
        labels={labels}
        read={read}
        path="events"
      />
      <Ledger
        title="Healing timeline"
        events={rows(combat.healing_events)}
        labels={labels}
        read={read}
        path="healing_events"
      />
      <Ledger
        title="Support timeline"
        events={rows(combat.support_events)}
        labels={labels}
        read={read}
        path="support_events"
      />
    </section>
  );
}
