export function endpoint(apiBase: string, path: string): string {
  return `${apiBase.replace(/\/$/, "")}/api/${path.replace(/^\//, "")}`;
}
export async function request<T>(
  apiBase: string,
  path: string,
  signal: AbortSignal,
  body?: unknown,
): Promise<T> {
  const response = await fetch(endpoint(apiBase, path), {
    signal,
    credentials: "same-origin",
    ...(body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
  });
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json"))
    throw new Error(
      response.status === 401 || response.status === 403
        ? "Sign in to use the calculator."
        : "The calculator service is unavailable. Try again.",
    );
  const data = await response.json();
  if (!response.ok || data.error)
    throw new Error(
      typeof data.error === "string"
        ? data.error
        : `The calculation could not finish (${response.status}).`,
    );
  return data as T;
}
