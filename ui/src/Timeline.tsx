"use client";

import { useRef, useState } from "react";
import "./timeline.css";
import type { AuthoredEvent } from "./scenario-state";
import type { EventActor, EventCapabilities } from "./EventEditor";

/** One thing the engine already scheduled, drawn as a ghost the user can read but not move. */
export interface ScheduledMark {
  actorId: string;
  time: number;
  kind: "cast" | "auto";
  label: string;
}

const TIME_STEP = 0.1;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/**
 * The fight as lanes on one time axis: every participant is a lane, the
 * engine's calculated casts and basic attacks are ghost marks, and authored
 * casts are markers the pointer drags along the axis. A click on an empty
 * stretch of a lane whose champion has authored-cast support adds a cast
 * there. Spell and recipient are edited in the table below the lanes; the
 * timeline owns only *when* and *who*, which is what a table cannot show.
 */
export function Timeline({
  enabled,
  onEnabled,
  duration,
  actors,
  events,
  onChange,
  capabilities,
  schedule,
  selectedId,
  onSelect,
}: {
  enabled: boolean;
  onEnabled: (value: boolean) => void;
  duration: number;
  actors: EventActor[];
  events: AuthoredEvent[];
  onChange: (events: AuthoredEvent[]) => void;
  capabilities: EventCapabilities;
  schedule: ScheduledMark[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const axis = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const ticks = Array.from({ length: Math.floor(duration) + 1 }, (_, i) => i);
  const supports = (actor: EventActor) =>
    Boolean(actor.champion && capabilities[actor.champion.name]);
  const slotsFor = (actor: EventActor) =>
    Object.keys(
      capabilities[actor.champion?.name ?? ""] ?? {},
    ) as AuthoredEvent["slot"][];
  const recipientsFor = (actor: EventActor, slot: string) => {
    const allowed =
      capabilities[actor.champion?.name ?? ""]?.[slot]?.recipients ?? [];
    return actors.filter((target) =>
      allowed.includes(
        target.id === actor.id
          ? "self"
          : target.team === actor.team
            ? "ally"
            : "enemy",
      ),
    );
  };
  const percent = (time: number) =>
    `${(clamp(time, 0, duration) / duration) * 100}%`;
  const timeAt = (clientX: number) => {
    const rect = axis.current?.getBoundingClientRect();
    if (!rect || !rect.width) return 0;
    const raw = ((clientX - rect.left) / rect.width) * duration;
    return Math.round(clamp(raw, 0, duration) / TIME_STEP) * TIME_STEP;
  };
  const setTime = (id: string, time: number) =>
    onChange(
      events.map((event) =>
        event.id === id ? { ...event, time: Number(time.toFixed(1)) } : event,
      ),
    );
  function addAt(actor: EventActor, time: number) {
    const slots = slotsFor(actor);
    const slot = slots.find((key) => (actor.ranks[key] ?? 0) > 0) ?? slots[0];
    if (!slot) return;
    const id = crypto.randomUUID();
    onChange([
      ...events,
      {
        id,
        time: Number(time.toFixed(1)),
        caster_id: actor.id,
        slot,
        recipient_id: recipientsFor(actor, slot)[0]?.id ?? "",
      },
    ]);
    onSelect(id);
  }
  return (
    <section className="calculator-timeline" aria-label="Fight timeline">
      <div className="calculator-section-heading">
        <div>
          <h2>Timeline</h2>
          <p>
            Ghost marks are the engine&apos;s schedule. Drag an authored cast to
            move it; click a lane to add one.
          </p>
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
      <div className="calculator-timeline-grid">
        <div className="calculator-timeline-corner" aria-hidden="true" />
        <div className="calculator-timeline-axis" ref={axis} aria-hidden="true">
          {ticks.map((tick) => (
            <span key={tick} style={{ left: percent(tick) }}>
              {tick}s
            </span>
          ))}
        </div>
        {actors.map((actor) => {
          const own = events.filter((event) => event.caster_id === actor.id);
          const ghosts = schedule.filter((mark) => mark.actorId === actor.id);
          const editable = enabled && supports(actor);
          return (
            <div className="calculator-timeline-row" key={actor.id}>
              <div className="calculator-timeline-label">
                {actor.champion?.icon && (
                  <img src={actor.champion.icon} alt="" />
                )}
                <span>{actor.label}</span>
                {!supports(actor) && <small>calculated schedule</small>}
              </div>
              <div
                className={`calculator-timeline-lane${editable ? " is-editable" : ""}`}
                onClick={(e) => {
                  if (!editable || e.target !== e.currentTarget) return;
                  addAt(actor, timeAt(e.clientX));
                }}
                role={editable ? "button" : undefined}
                tabIndex={editable ? 0 : undefined}
                aria-label={
                  editable
                    ? `${actor.label}: add a cast on the timeline`
                    : undefined
                }
                onKeyDown={(e) => {
                  if (editable && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    addAt(actor, 0);
                  }
                }}
              >
                {ticks.map((tick) => (
                  <i key={tick} style={{ left: percent(tick) }} />
                ))}
                {ghosts.map((mark, index) => (
                  <span
                    key={index}
                    className={`calculator-timeline-ghost is-${mark.kind}`}
                    style={{ left: percent(mark.time) }}
                    title={`${mark.label} at ${mark.time.toFixed(1)}s (engine schedule)`}
                  >
                    {mark.kind === "cast" ? mark.label : ""}
                  </span>
                ))}
                {own.map((event) => (
                  <button
                    type="button"
                    key={event.id}
                    className={`calculator-timeline-mark${selectedId === event.id ? " is-selected" : ""}${dragging === event.id ? " is-dragging" : ""}`}
                    style={{ left: percent(event.time) }}
                    aria-label={`${actor.label} ${event.slot} at ${event.time.toFixed(1)} seconds; drag or use arrow keys to move`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelect(event.id);
                    }}
                    onPointerDown={(e) => {
                      if (!enabled) return;
                      e.currentTarget.setPointerCapture(e.pointerId);
                      setDragging(event.id);
                      onSelect(event.id);
                    }}
                    onPointerMove={(e) => {
                      if (dragging !== event.id) return;
                      setTime(event.id, timeAt(e.clientX));
                    }}
                    onPointerUp={() => setDragging(null)}
                    onPointerCancel={() => setDragging(null)}
                    onKeyDown={(e) => {
                      const delta =
                        e.key === "ArrowRight"
                          ? TIME_STEP
                          : e.key === "ArrowLeft"
                            ? -TIME_STEP
                            : 0;
                      if (!delta || !enabled) return;
                      e.preventDefault();
                      setTime(event.id, clamp(event.time + delta, 0, duration));
                    }}
                  >
                    {event.slot}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {!actors.length && (
        <p className="calculator-event-help">
          Choose champions in the Teams step to see their lanes.
        </p>
      )}
    </section>
  );
}
