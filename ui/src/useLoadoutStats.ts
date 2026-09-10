import { useEffect, useState } from "react";
import { request } from "./api";

export function useLoadoutStats(
  apiBase: string,
  body: Record<string, unknown> | null,
) {
  const key = JSON.stringify(body);
  const [result, setResult] = useState<{
    key: string;
    stats: Record<string, number> | null;
    error?: string;
  }>({ key: "", stats: null });
  useEffect(() => {
    if (key === "null") return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      request<{ stats: Record<string, number> }>(
        apiBase,
        "loadout-stats",
        controller.signal,
        JSON.parse(key),
      )
        .then((data) => {
          if (!controller.signal.aborted) setResult({ key, stats: data.stats });
        })
        .catch((error) => {
          if (!controller.signal.aborted)
            setResult({ key, stats: null, error: error.message });
        });
    }, 400);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [apiBase, key]);
  return {
    stats: result.key === key ? result.stats : null,
    loading: key !== "null" && result.key !== key,
    error: result.key === key ? result.error : undefined,
  };
}
