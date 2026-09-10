import { useEffect, useRef, useState } from "react";
import { request } from "./api";

interface Candidate {
  name: string;
  icon?: string;
  score?: number;
  objective_value?: number;
  metric?: string;
  timeline_coverage?: { complete?: boolean };
}
interface SlotResult {
  candidates?: Candidate[];
  partial_candidates?: Candidate[];
  withheld_candidates?: { name?: string; reason?: string; detail?: string }[];
  candidate_count?: number;
  evaluated_count?: number;
  coverage?: { complete?: boolean; note?: string; [key: string]: unknown };
}
const display = (value: number | undefined) =>
  typeof value === "number"
    ? value.toLocaleString("en-US", { maximumFractionDigits: 1 })
    : "—";
export function SlotSearch({
  apiBase,
  body,
  title,
  ready,
  objective,
  objectives,
  onObjective,
  onPick,
}: {
  apiBase: string;
  body: Record<string, unknown>;
  title: string;
  ready: string;
  objective: string;
  objectives: Record<string, { label: string; description?: string }>;
  onObjective: (value: string) => void;
  onPick: (name: string) => void;
}) {
  const [result, setResult] = useState<SlotResult | null>(null);
  const [resultKey, setResultKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const active = useRef<AbortController | null>(null);
  const cache = useRef(new Map<string, SlotResult>());
  const key = JSON.stringify({ apiBase, body });
  const [previousInput, setPreviousInput] = useState(key);
  if (previousInput !== key) {
    setPreviousInput(key);
    setBusy(false);
    setError("");
  }
  useEffect(() => {
    active.current?.abort();
  }, [key]);
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    if (!busy) return;
    const start = Date.now();
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [busy]);
  async function search() {
    const cached = cache.current.get(key);
    if (cached) {
      setResult(cached);
      setResultKey(key);
      return;
    }
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    setElapsed(0);
    try {
      const next = await request<SlotResult>(
        apiBase,
        "bis",
        controller.signal,
        body,
      );
      if (controller.signal.aborted) return;
      if (cache.current.size >= 12)
        cache.current.delete(cache.current.keys().next().value!);
      cache.current.set(key, next);
      setResult(next);
      setResultKey(key);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  const fresh = resultKey === key;
  return (
    <>
      <div className="calculator-slot-search-bar">
        <div>
          <strong>{title}</strong>
          <span>Compare one item. Other slots stay fixed.</span>
        </div>
        <label>
          <span>Rank by</span>
          <select
            aria-label="Item slot objective"
            value={objective}
            onChange={(e) => onObjective(e.target.value)}
          >
            {Object.entries(objectives).map(([value, definition]) => (
              <option value={value} key={value}>
                {definition.label}
              </option>
            ))}
          </select>
        </label>
        {busy ? (
          <button
            type="button"
            onClick={() => {
              active.current?.abort();
              setBusy(false);
            }}
          >
            Cancel search · {elapsed}s
          </button>
        ) : (
          <button
            type="button"
            className="calculator-primary"
            disabled={Boolean(ready)}
            onClick={search}
          >
            Rank this slot
          </button>
        )}
      </div>
      {ready && <p>{ready}</p>}
      {!ready && objectives[objective]?.description && (
        <p className="calculator-slot-search-note">
          {objectives[objective].description}
        </p>
      )}
      {busy && (
        <p role="status">Evaluating legal items in this fight… {elapsed}s</p>
      )}
      {error && (
        <p role="alert">
          {error} Try a shorter fight or fewer participants, then rank again.
        </p>
      )}
      {result && fresh && !busy && (
        <div className="calculator-slot-search-results">
          {Boolean(result.candidates?.length) && (
            <>
              <p>
                {result.candidates!.length} ranked candidates
                {result.coverage?.complete
                  ? " · Candidate coverage complete"
                  : " · Limited candidate coverage"}
              </p>
              <ol>
                {result.candidates!.slice(0, 8).map((candidate) => (
                  <li key={candidate.name}>
                    <button
                      type="button"
                      onClick={() => onPick(candidate.name)}
                      aria-label={`Equip ${candidate.name} in selected slot`}
                    >
                      {candidate.icon && <img src={candidate.icon} alt="" />}
                      <strong>{candidate.name}</strong>
                      <span>
                        {display(candidate.objective_value ?? candidate.score)}
                      </span>
                      <span>Equip</span>
                    </button>
                  </li>
                ))}
              </ol>
            </>
          )}
          {!result.candidates?.length && (
            <p role="status">
              No item has a certified rank for this setup. The shop remains
              available for manual selection.
            </p>
          )}
          {Boolean(
            result.partial_candidates?.length ||
              result.withheld_candidates?.length,
          ) && (
            <details>
              <summary>
                Coverage details ·{" "}
                {(result.partial_candidates?.length ?? 0) +
                  (result.withheld_candidates?.length ?? 0)}{" "}
                unranked items
              </summary>
              <p>
                These items have incomplete event coverage or a source
                restriction.
              </p>
              <ul>
                {result.partial_candidates?.map((candidate) => (
                  <li key={candidate.name}>
                    {candidate.name} · incomplete event order
                  </li>
                ))}
                {result.withheld_candidates?.map((candidate, index) => (
                  <li key={index}>
                    {candidate.name} ·{" "}
                    {candidate.detail ?? candidate.reason ?? "withheld"}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </>
  );
}
