import { useEffect, useRef, useState } from "react";
import { request } from "./api";
interface PurchaseResult {
  items?: string[];
  boots?: string;
  purchase_items?: string[];
  sell_items?: string[];
  recommendation_type?: string;
  spent_gold?: number;
  remaining_gold?: number;
  damage_delta_vs_current?: number;
  winner_event_order_certified?: boolean;
  search_guarantee?: string;
  price_rows?: unknown[];
  search_timeline_coverage?: { note?: string };
}
export function PurchasePlanner({
  apiBase,
  body,
  onApply,
  disabled,
}: {
  apiBase: string;
  body: Record<string, unknown>;
  onApply: (items: string[], boots: string) => void;
  disabled: boolean;
}) {
  const [gold, setGold] = useState("1000");
  const [sell, setSell] = useState(false);
  const [result, setResult] = useState<PurchaseResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState("");
  const active = useRef<AbortController | null>(null);
  const input = JSON.stringify({ body, gold, sell });
  const [previousInput, setPreviousInput] = useState(input);
  if (previousInput !== input) {
    setPreviousInput(input);
    setBusy(false);
    setError("");
  }
  useEffect(() => {
    active.current?.abort();
  }, [input]);
  useEffect(() => () => active.current?.abort(), []);
  async function find() {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    try {
      const next = await request<PurchaseResult>(
        apiBase,
        "optimize",
        controller.signal,
        {
          ...body,
          optimization_scope: "purchase",
          available_gold: Number(gold),
          allow_sell: sell,
          max_sell_items: 1,
          combine_policy: "shop_combine",
          max_purchase_items: 1,
          objective: "total_damage",
          locked_items: body.items,
          locked_boots: body.boots,
        },
      );
      if (!controller.signal.aborted) {
        setResult(next);
        setKey(input);
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  const fmt = (value: number | undefined) =>
    value === undefined
      ? "—"
      : value.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return (
    <details className="calculator-purchase-planner">
      <summary>Plan a purchase with gold in hand</summary>
      <p>
        Compare one purchase for your champion’s damage. Existing components
        receive shop credit.
      </p>
      <div className="calculator-slot-search-bar">
        <label>
          <span>Gold in hand</span>
          <input
            type="number"
            min={1}
            max={30000}
            value={gold}
            onChange={(event) => setGold(event.target.value)}
          />
        </label>
        <label className="calculator-check">
          <input
            type="checkbox"
            checked={sell}
            onChange={(event) => setSell(event.target.checked)}
          />
          Allow one item sale
        </label>
        {busy ? (
          <button
            type="button"
            onClick={() => {
              active.current?.abort();
              setBusy(false);
            }}
          >
            Cancel purchase search
          </button>
        ) : (
          <button
            type="button"
            disabled={
              disabled ||
              !Number.isInteger(Number(gold)) ||
              Number(gold) < 1 ||
              Number(gold) > 30000
            }
            onClick={find}
          >
            Find next purchase
          </button>
        )}
      </div>
      {busy && <p role="status">Evaluating purchase plans…</p>}
      {error && <p role="alert">{error}</p>}
      {result && key === input && !busy && (
        <div>
          {result.recommendation_type === "no_affordable_purchase" ? (
            <p>No legal purchase fits this amount of gold.</p>
          ) : (
            <>
              <p>
                <strong>Buy {result.purchase_items?.join(" + ") || "—"}</strong>
                {result.sell_items?.length
                  ? ` · Sell ${result.sell_items.join(" + ")}`
                  : ""}
              </p>
              <p>
                {fmt(result.spent_gold)} gold spent ·{" "}
                {fmt(result.remaining_gold)} gold left ·{" "}
                {fmt(result.damage_delta_vs_current)} damage change
              </p>
              <p>{result.search_guarantee?.replaceAll("_", " ")}</p>
              {result.winner_event_order_certified ? (
                <button
                  type="button"
                  onClick={() =>
                    onApply(result.items ?? [], result.boots ?? "")
                  }
                >
                  Apply purchase plan
                </button>
              ) : (
                <p>
                  {result.search_timeline_coverage?.note ??
                    "Event coverage is incomplete. This plan remains unconfirmed."}
                </p>
              )}
              <details>
                <summary>Shop calculation</summary>
                <pre>{JSON.stringify(result.price_rows, null, 2)}</pre>
              </details>
            </>
          )}
        </div>
      )}
    </details>
  );
}
