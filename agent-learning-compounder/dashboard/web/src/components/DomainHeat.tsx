import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardData } from "@/lib/data";
import { allDomains, domainHeatRows } from "@/lib/data";

const CHART_COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
];

export function DomainHeat({ data }: { data: DashboardData }) {
  const rows = domainHeatRows(data.history);
  const domains = allDomains(data.history);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Per-domain evidence over time</CardTitle>
        <p className="mt-1 text-xs italic text-muted-foreground">
          Stacked bar — which topics dominate the run, week over week.
        </p>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <div className="flex h-[260px] items-center justify-center rounded-md border border-dashed text-sm italic text-muted-foreground">
            No history yet.
          </div>
        ) : (
          <div className="h-[260px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis
                  dataKey="date"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  minTickGap={24}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  width={36}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                />
                <Tooltip
                  cursor={{ fill: "hsl(var(--muted))", opacity: 0.4 }}
                  content={({ active, payload, label }) => {
                    if (!active || !payload || !payload.length) return null;
                    return (
                      <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
                        <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                          {label}
                        </div>
                        <div className="mt-1 grid gap-1 font-mono text-[12px]">
                          {payload.map((p) => (
                            <div key={p.dataKey as string} className="flex items-center gap-2">
                              <span className="inline-block h-2 w-2 rounded-sm" style={{ background: String(p.color) }} />
                              <span className="text-muted-foreground">{p.dataKey as string}</span>
                              <span className="ml-auto tabular-nums text-foreground">{String(p.value)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, color: "hsl(var(--muted-foreground))" }}
                  iconType="square"
                />
                {domains.map((d, i) => (
                  <Bar
                    key={d}
                    dataKey={d}
                    stackId="a"
                    fill={CHART_COLORS[i % CHART_COLORS.length]}
                    isAnimationActive={false}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
