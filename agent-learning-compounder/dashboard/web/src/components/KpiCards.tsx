import { Card, CardContent, CardTitle } from "@/components/ui/card";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import type { DashboardData } from "@/lib/data";
import { trendSeries } from "@/lib/data";
import { formatNum } from "@/lib/utils";

interface Props {
  data: DashboardData;
}

interface Kpi {
  key: "gates" | "evidence_lines" | "corpus_meta" | "user_lines" | "skill_alerts";
  label: string;
  hint: string;
}

const KPIS: Kpi[] = [
  { key: "gates", label: "Rules surfaced", hint: "patterns the next agent must clear" },
  { key: "evidence_lines", label: "Feedback lines", hint: "user messages backing the rules" },
  { key: "corpus_meta", label: "Session roots", hint: "transcript trees mined this run" },
  { key: "user_lines", label: "User messages", hint: "across the sampled corpus" },
  { key: "skill_alerts", label: "Skill alerts", hint: "broken or missed skills" },
];

export function KpiCards({ data }: Props) {
  const latest = data.latest?.totals;
  const history = data.history;
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
      {KPIS.map((kpi) => {
        const series = trendSeries(history, kpi.key as any);
        const value = latest ? (latest as any)[kpi.key] : (series.at(-1)?.value ?? 0);
        const prev = series.length > 1 ? series.at(-2)?.value : undefined;
        const delta = value != null && prev != null ? value - prev : undefined;
        return (
          <Card key={kpi.key} className="group relative overflow-hidden">
            <CardContent className="p-4 pb-3">
              <CardTitle className="text-[10px]">{kpi.label}</CardTitle>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-3xl font-semibold tabular-nums tracking-tight">
                  {formatNum(value as number)}
                </span>
                {delta != null && delta !== 0 && (
                  <span
                    className={`font-mono text-[10px] uppercase tracking-wider ${
                      delta > 0 ? "text-accent" : "text-muted-foreground"
                    }`}
                  >
                    {delta > 0 ? "+" : ""}
                    {delta}
                  </span>
                )}
              </div>
              <p className="mt-1 text-[11px] italic text-muted-foreground">{kpi.hint}</p>
              {series.length > 1 && (
                <div className="mt-3 h-9 -mx-1">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={series} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
                      <defs>
                        <linearGradient id={`spark-${kpi.key}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.4} />
                          <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <Area
                        type="monotone"
                        dataKey="value"
                        stroke="hsl(var(--accent))"
                        strokeWidth={1.5}
                        fill={`url(#spark-${kpi.key})`}
                        isAnimationActive={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
