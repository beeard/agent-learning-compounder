import { useCallback, useEffect, useState } from "react";

export interface ConnectionState {
  online: boolean;
  origin: string;
  pingedAt: string | null;
  version: string | null;
  personal: string | null;
  bundlePresent: boolean | null;
  autoDistill: boolean | null;
  error: string | null;
}

const HEALTH_PATH = "/api/health";

function sameOriginHttp(): boolean {
  if (typeof window === "undefined") return false;
  return window.location.protocol === "http:" || window.location.protocol === "https:";
}

async function ping(): Promise<Partial<ConnectionState> | null> {
  try {
    const res = await fetch(HEALTH_PATH, { cache: "no-store" });
    if (!res.ok) return null;
    const body = await res.json();
    return {
      version: body.version ?? null,
      personal: body.personal ?? null,
      bundlePresent: body.bundle_present ?? null,
      autoDistill: body.auto_distill ?? null,
      pingedAt: body.ts ?? new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

export function useConnection(pollMs = 30_000): ConnectionState & {
  refresh: () => Promise<void>;
} {
  const [state, setState] = useState<ConnectionState>({
    online: false,
    origin: typeof window !== "undefined" ? window.location.origin : "file://",
    pingedAt: null,
    version: null,
    personal: null,
    bundlePresent: null,
    autoDistill: null,
    error: sameOriginHttp() ? null : "loaded via file:// — actions need serve_dashboard.py",
  });

  const refresh = useCallback(async () => {
    if (!sameOriginHttp()) {
      setState((s) => ({ ...s, online: false }));
      return;
    }
    const result = await ping();
    setState((s) => ({
      ...s,
      ...(result ?? {}),
      online: result != null,
      error: result ? null : "API unreachable",
    }));
  }, []);

  useEffect(() => {
    refresh();
    if (!sameOriginHttp()) return;
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [pollMs, refresh]);

  return { ...state, refresh };
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch {
      /* noop */
    }
    throw new Error(`POST ${path}: ${detail}`);
  }
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path}: ${res.statusText}`);
  return (await res.json()) as T;
}
