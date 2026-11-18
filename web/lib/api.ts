"use client";

import useSWR, { type SWRConfiguration } from "swr";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Thin fetch wrapper: same-origin /api, JSON in and out, typed errors. */
export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      credentials: "same-origin",
      ...rest,
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the Opscend API. Is it running on :8000?");
  }
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      const d = body?.detail;
      message = typeof d === "string" ? d : (d?.message ?? d?.[0]?.msg ?? JSON.stringify(body));
    } catch {
      // Next's proxy answers 500 with a text body when the API is down.
      if (res.status >= 500) message = "Cannot reach the Opscend API. Is it running on :8000?";
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export function useApi<T>(path: string | null, config?: SWRConfiguration<T, ApiError>) {
  return useSWR<T, ApiError>(path, (p: string) => api<T>(p), {
    revalidateOnFocus: true,
    shouldRetryOnError: (e) => e.status !== 401 && e.status !== 404,
    errorRetryInterval: 4000,
    keepPreviousData: true,
    ...config,
  });
}
