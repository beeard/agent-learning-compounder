/**
 * Typed accessors for the live data injected into the dashboard at build/render
 * time. The Python wrapper replaces the JSON payload inside
 * <script id="alc-payload" type="application/json">…</script>.
 */

export interface GateRow {
  domain: string;
  level: string;
  count: number;
  source_count?: number;
  session_refs?: string[];
  failure_signal?: string;
  gate: string;
  gate_category: string;
  quote?: string;
  evidence_label?: string;
}

export interface Totals {
  user_lines: number;
  assistant_lines: number;
  corpus_meta: number;
  domain_rules: number;
  gates: number;
  evidence_lines: number;
  evidence_fallback?: number;
  skills_available: number;
  skill_alerts: number;
}

export interface ReportPayload {
  date: string;
  mode: string;
  repo: string | null;
  totals: Totals;
  agent_compensation: { rows: GateRow[]; default?: string | null };
  memory_derived?: { rows: GateRow[]; evidence_fallback?: string[]; had_data: boolean };
  skill_inventory?: {
    available_count: number;
    invalid_count: number;
    rows: { name: string; path: string }[];
    omitted?: number;
  };
  skill_usage?: { expected: string[]; loaded: string[]; applied: string[] };
  skill_health?: { invalid: string[]; missed: string[]; failed_to_apply: string[] };
  skill_compensation?: { rows: { skill: string; signal: string; gate: string; count: number }[] };
  domain_rules: { count: number; source?: string | null };
  prior_report_path?: string | null;
  corpus_meta?: string[];
  next_agent_brief?: string[];
  needs_verification?: string[];
}

export interface MetricsRow {
  ts: string;
  date: string;
  mode: string;
  repo: string | null;
  totals: Totals;
  by_level: Record<string, number>;
  by_domain: { domain: string; level: string; count: number; sessions: number; gate_category: string }[];
  domain_rules: { count: number; source?: string | null };
  prior_report?: string | null;
}

export interface DashboardData {
  generated_at: string;
  personal_root: string;
  latest: ReportPayload | null;
  history: MetricsRow[];
}

const placeholder: DashboardData = {
  generated_at: new Date().toISOString(),
  personal_root: "(no payload)",
  latest: null,
  history: [],
};

export function readDashboardData(): DashboardData {
  if (typeof document === "undefined") return placeholder;
  const el = document.getElementById("alc-payload");
  if (!el) return placeholder;
  try {
    const parsed = JSON.parse(el.textContent ?? "");
    if (parsed && parsed._placeholder) return placeholder;
    return parsed as DashboardData;
  } catch {
    return placeholder;
  }
}

// ----- derived helpers -----

export function trendSeries(
  history: MetricsRow[],
  key: "gates" | "evidence_lines" | "user_lines" | "corpus_meta",
): { date: string; ts: string; value: number }[] {
  return history.map((row) => ({
    date: row.date,
    ts: row.ts,
    value: row.totals[key] ?? 0,
  }));
}

export function domainHeatRows(history: MetricsRow[]): {
  date: string;
  ts: string;
  [domain: string]: number | string;
}[] {
  return history.map((row) => {
    const acc: any = { date: row.date, ts: row.ts };
    for (const d of row.by_domain ?? []) {
      acc[d.domain] = (acc[d.domain] ?? 0) + (d.count ?? 0);
    }
    return acc;
  });
}

export function allDomains(history: MetricsRow[]): string[] {
  const set = new Set<string>();
  for (const r of history) for (const d of r.by_domain ?? []) set.add(d.domain);
  return Array.from(set).sort();
}

export interface GateStabilityRow {
  key: string;
  domain: string;
  gate_category: string;
  runs: number;
  total_runs: number;
  stability: number; // 0..1 ratio of runs containing this key
  last_seen: string;
  best_level: string;
}

export function gateStability(history: MetricsRow[]): GateStabilityRow[] {
  if (history.length === 0) return [];
  const byKey = new Map<string, GateStabilityRow>();
  for (const r of history) {
    for (const d of r.by_domain ?? []) {
      const key = `${d.domain}::${d.gate_category}`;
      const existing = byKey.get(key);
      if (existing) {
        existing.runs += 1;
        existing.last_seen = r.ts;
        if (levelRank(d.level) > levelRank(existing.best_level)) existing.best_level = d.level;
      } else {
        byKey.set(key, {
          key,
          domain: d.domain,
          gate_category: d.gate_category,
          runs: 1,
          total_runs: history.length,
          stability: 0,
          last_seen: r.ts,
          best_level: d.level,
        });
      }
    }
  }
  return Array.from(byKey.values())
    .map((row) => ({ ...row, stability: row.runs / history.length }))
    .sort((a, b) => b.stability - a.stability || b.runs - a.runs);
}

export function levelRank(level: string): number {
  if (level === "3") return 3;
  if (level === "2") return 2;
  return 1;
}

export function levelLabel(level: string): { label: string; tone: "high" | "mid" | "low" } {
  if (level === "3") return { label: "High", tone: "high" };
  if (level === "2") return { label: "Medium", tone: "mid" };
  return { label: "Low", tone: "low" };
}
