"use client";

import { useEffect, useRef, useState } from "react";
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

const SNAP_STEPS = [0.1, 0.25, 0.5, 1] as const;
const ZOOM_MIN = 40;
const ZOOM_MAX = 200;
const CLIP_WIDTH = 34;
const SLOT_ORDER: AuthoredEvent["slot"][] = ["Q", "W", "E", "R"];
const DRAG_TYPE = "application/x-calculator-cast";

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/**
 * The fight as a piano roll: one lane per champion, that champion's spell
 * icons as a palette at the lane head, and every authored cast a block on a
 * time grid. Drag an icon onto a lane to place a cast where it lands, drag a
 * block to move it, pick a block to set its recipient. The engine's own
 * schedule shows as ghost blocks so the authored series reads against it.
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
  const roll = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(80);
  const [snap, setSnap] = useState<(typeof SNAP_STEPS)[number]>(0.25);
  const [dragging, setDragging] = useState<{
    id: string;
    offset: number;
  } | null>(null);
  const width = Math.max(1, duration * zoom);
  const supports = (actor: EventActor) =>
    Boolean(actor.champion && capabilities[actor.champion.name]);
  const slotsFor = (actor: EventActor) =>
    SLOT_ORDER.filter((slot) =>
      Boolean(capabilities[actor.champion?.name ?? ""]?.[slot]),
    );
  const reachOf = (actor: EventActor, slot: string) =>
    capabilities[actor.champion?.name ?? ""]?.[slot]?.reach;
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
  const snapped = (time: number) =>
    Number((Math.round(clamp(time, 0, duration) / snap) * snap).toFixed(2));
  const timeAt = (clientX: number, lane: HTMLElement) => {
    const rect = lane.getBoundingClientRect();
    return snapped(((clientX - rect.left) / rect.width) * duration);
  };
  const left = (time: number) =>
    `${(clamp(time, 0, duration) / duration) * 100}%`;
  const edit = (id: string, change: Partial<AuthoredEvent>) =>
    onChange(
      events.map((event) =>
        event.id === id ? { ...event, ...change } : event,
      ),
    );
  const remove = (id: string) => {
    onChange(events.filter((event) => event.id !== id));
    if (selectedId === id) onSelect("");
  };
  function place(actor: EventActor, slot: AuthoredEvent["slot"], time: number) {
    const id = crypto.randomUUID();
    onChange([
      ...events,
      {
        id,
        time: snapped(time),
        caster_id: actor.id,
        slot,
        recipient_id: recipientsFor(actor, slot)[0]?.id ?? "",
      },
    ]);
    onSelect(id);
  }
  /* Click on a palette icon appends the cast half a step after the
   * champion's last authored cast, so a series builds left to right. */
  function append(actor: EventActor, slot: AuthoredEvent["slot"]) {
    const own = events.filter((event) => event.caster_id === actor.id);
    const last = own.length
      ? Math.max(...own.map((event) => event.time))
      : -snap;
    place(actor, slot, Math.min(duration, last + snap * 2));
  }
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!selectedId || !enabled) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest?.("input, select, textarea")) return;
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        remove(selectedId);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, enabled, events]);

  const ticks: number[] = [];
  for (let t = 0; t <= duration + 1e-9; t += 0.5)
    ticks.push(Number(t.toFixed(2)));
  const selected = events.find((event) => event.id === selectedId) ?? null;
  const selectedActor = selected
    ? actors.find((actor) => actor.id === selected.caster_id)
    : undefined;

  return (
    <section className="calculator-timeline" aria-label="Fight timeline">
      <div className="calculator-section-heading">
        <div>
          <h2>Timeline</h2>
          <p>
            Drag a spell from a lane head onto the lane, or click it to append.
            Drag blocks to move them; Delete removes the selected one.
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
      <div
        className="calculator-roll-toolbar"
        role="toolbar"
        aria-label="Timeline tools"
      >
        <label>
          <span>Zoom</span>
          <input
            type="range"
            min={ZOOM_MIN}
            max={ZOOM_MAX}
            step={10}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
            aria-label="Timeline zoom, pixels per second"
          />
        </label>
        <label>
          <span>Snap</span>
          <select
            value={snap}
            onChange={(e) =>
              setSnap(Number(e.target.value) as (typeof SNAP_STEPS)[number])
            }
            aria-label="Snap step in seconds"
          >
            {SNAP_STEPS.map((step) => (
              <option key={step} value={step}>
                {step}s
              </option>
            ))}
          </select>
        </label>
        <span className="calculator-roll-count" role="status">
          {events.length
            ? `${events.length} authored cast${events.length === 1 ? "" : "s"}`
            : "No authored casts"}
        </span>
        {events.length > 0 && (
          <button
            type="button"
            className="calculator-text-button"
            onClick={() => {
              onChange([]);
              onSelect("");
            }}
          >
            Clear all
          </button>
        )}
      </div>
      <div className="calculator-roll" ref={roll}>
        <div className="calculator-roll-heads">
          <div className="calculator-roll-corner" aria-hidden="true" />
          {actors.map((actor) => {
            const slots = slotsFor(actor);
            return (
              <div className="calculator-roll-head" key={actor.id}>
                <div className="calculator-roll-identity">
                  {actor.champion?.icon && (
                    <img src={actor.champion.icon} alt="" />
                  )}
                  <span>{actor.label}</span>
                </div>
                {supports(actor) ? (
                  <div
                    className="calculator-roll-palette"
                    role="group"
                    aria-label={`${actor.label} spells`}
                  >
                    {slots.map((slot) => {
                      const ability = actor.champion?.abilities[slot];
                      const learned = (actor.ranks[slot] ?? 0) > 0;
                      return (
                        <button
                          type="button"
                          key={slot}
                          className={`calculator-roll-spell${learned ? "" : " is-unlearned"}`}
                          draggable={enabled}
                          disabled={!enabled}
                          title={`${slot} · ${ability?.name ?? slot}${learned ? "" : " (unlearned)"}${reachOf(actor, slot) === "every_enemy" ? " · every enemy" : ""}`}
                          aria-label={`${actor.label}: add ${slot} ${ability?.name ?? ""}`}
                          onClick={() => append(actor, slot)}
                          onDragStart={(e) => {
                            e.dataTransfer.setData(
                              DRAG_TYPE,
                              JSON.stringify({ actorId: actor.id, slot }),
                            );
                            e.dataTransfer.effectAllowed = "copy";
                          }}
                        >
                          {ability?.icon ? (
                            <img src={ability.icon} alt="" />
                          ) : (
                            <span>{slot}</span>
                          )}
                          <b>{slot}</b>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <small>calculated schedule</small>
                )}
              </div>
            );
          })}
        </div>
        <div className="calculator-roll-scroll">
          <div className="calculator-roll-grid" style={{ width }}>
            <div className="calculator-roll-ruler" aria-hidden="true">
              {ticks.map((tick) => (
                <span
                  key={tick}
                  className={Number.isInteger(tick) ? "is-major" : ""}
                  style={{ left: left(tick) }}
                >
                  {Number.isInteger(tick) ? `${tick}s` : ""}
                </span>
              ))}
            </div>
            {actors.map((actor) => {
              const own = events.filter(
                (event) => event.caster_id === actor.id,
              );
              const ghosts = schedule.filter(
                (mark) => mark.actorId === actor.id,
              );
              const editable = enabled && supports(actor);
              return (
                <div
                  className={`calculator-roll-lane${editable ? " is-editable" : ""}`}
                  key={actor.id}
                  onDragOver={(e) => {
                    if (editable && e.dataTransfer.types.includes(DRAG_TYPE))
                      e.preventDefault();
                  }}
                  onDrop={(e) => {
                    if (!editable) return;
                    const raw = e.dataTransfer.getData(DRAG_TYPE);
                    if (!raw) return;
                    e.preventDefault();
                    const { actorId, slot } = JSON.parse(raw) as {
                      actorId: string;
                      slot: AuthoredEvent["slot"];
                    };
                    if (actorId !== actor.id) return;
                    place(actor, slot, timeAt(e.clientX, e.currentTarget));
                  }}
                  onPointerMove={(e) => {
                    if (!dragging) return;
                    const event = own.find((row) => row.id === dragging.id);
                    if (!event) return;
                    edit(event.id, {
                      time: timeAt(
                        e.clientX - dragging.offset,
                        e.currentTarget,
                      ),
                    });
                  }}
                  onPointerUp={() => setDragging(null)}
                  onPointerCancel={() => setDragging(null)}
                >
                  {ticks.map((tick) => (
                    <i
                      key={tick}
                      className={Number.isInteger(tick) ? "is-major" : ""}
                      style={{ left: left(tick) }}
                    />
                  ))}
                  {ghosts.map((mark, index) => (
                    <span
                      key={index}
                      className={`calculator-roll-ghost is-${mark.kind}`}
                      style={{ left: left(mark.time) }}
                      title={`${mark.label} at ${mark.time.toFixed(2)}s (engine schedule)`}
                    >
                      {mark.kind === "cast" ? mark.label : ""}
                    </span>
                  ))}
                  {own.map((event) => {
                    const ability = actor.champion?.abilities[event.slot];
                    const recipient = actors.find(
                      (target) => target.id === event.recipient_id,
                    );
                    return (
                      <button
                        type="button"
                        key={event.id}
                        className={`calculator-roll-clip${selectedId === event.id ? " is-selected" : ""}${dragging?.id === event.id ? " is-dragging" : ""}`}
                        style={{ left: left(event.time), width: CLIP_WIDTH }}
                        aria-label={`${actor.label} ${event.slot} at ${event.time.toFixed(2)} seconds on ${recipient?.label ?? "no recipient"}; drag or use arrow keys to move`}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelect(event.id);
                        }}
                        onPointerDown={(e) => {
                          if (!enabled) return;
                          const rect = e.currentTarget.getBoundingClientRect();
                          e.currentTarget.releasePointerCapture?.(e.pointerId);
                          setDragging({
                            id: event.id,
                            offset: e.clientX - rect.left,
                          });
                          onSelect(event.id);
                        }}
                        onKeyDown={(e) => {
                          const delta =
                            e.key === "ArrowRight"
                              ? snap
                              : e.key === "ArrowLeft"
                                ? -snap
                                : 0;
                          if (!delta || !enabled) return;
                          e.preventDefault();
                          edit(event.id, { time: snapped(event.time + delta) });
                        }}
                      >
                        {ability?.icon ? (
                          <img src={ability.icon} alt="" />
                        ) : (
                          <span>{event.slot}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {!actors.length && (
        <p className="calculator-event-help">
          Choose champions in the Teams step to see their lanes.
        </p>
      )}
      {selected && selectedActor && (
        <div
          className="calculator-roll-inspector"
          role="group"
          aria-label="Selected cast"
        >
          <strong>
            {selectedActor.label} · {selected.slot}{" "}
            {selectedActor.champion?.abilities[selected.slot]?.name ?? ""}
          </strong>
          <label>
            <span>Time</span>
            <input
              type="number"
              min={0}
              max={duration}
              step={snap}
              value={selected.time}
              onChange={(e) =>
                edit(selected.id, { time: snapped(Number(e.target.value)) })
              }
            />
            <span>s</span>
          </label>
          <label>
            <span>Recipient</span>
            <select
              value={selected.recipient_id}
              onChange={(e) =>
                edit(selected.id, { recipient_id: e.target.value })
              }
            >
              {!recipientsFor(selectedActor, selected.slot).some(
                (target) => target.id === selected.recipient_id,
              ) && <option value="">Choose a legal recipient</option>}
              {recipientsFor(selectedActor, selected.slot).map((target) => (
                <option key={target.id} value={target.id}>
                  {target.label}
                  {target.id === selectedActor.id ? " (self)" : ""}
                </option>
              ))}
            </select>
          </label>
          {reachOf(selectedActor, selected.slot) === "every_enemy" && (
            <small>Area cast: reaches every enemy whoever is named.</small>
          )}
          {(selectedActor.ranks[selected.slot] ?? 0) === 0 && (
            <small>
              Unlearned at this level; the engine will refuse the cast.
            </small>
          )}
          <button
            type="button"
            className="calculator-text-button"
            onClick={() => remove(selected.id)}
          >
            Remove
          </button>
        </div>
      )}
    </section>
  );
}
