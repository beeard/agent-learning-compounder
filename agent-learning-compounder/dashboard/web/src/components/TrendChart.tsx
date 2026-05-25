import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardData } from "@/lib/data";
import { trendSeries } from "@/lib/data";

interface Props {
  data: DashboardData;
}

const METRICS = [
  { key: "gates", label: "Rules" },
  { key: "evidence_lines", label: "Feedback lines" },
  { key: "user_lines", label: "User messages" },
] as const;

export function TrendChart({ data }: Props) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <div>
          <CardTitle>Tracking · last {data.history.length} runs</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground italic">
            How key metrics have moved across recent --write runs.
          </p>
        </div>
      </CardHeader>
      <CardContent className="pt-4">
        <Tabs defaultValue="gates" className="w-full">
          <TabsList>
            {METRICS.map((m) => (
              <TabsTrigger key={m.key} value={m.key}>
                {m.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {METRICS.map((m) => {
            const series = trendSeries(data.history, m.key as any);
            return (
              <TabsContent key={m.key} value={m.key}>
                {series.length === 0 ? (
                  <EmptyChart message="No runs recorded yet. Run distill --write to start tracking." />
                ) : (
                  <div className="h-[220px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={series} margin={{ top: 16, right: 24, left: 0, bottom: 0 }}>
                        <defs>
                          <linearGradient id={`grad-${m.key}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.35} />
                            <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid vertical={false} />
                        <XAxis
                          dataKey="date"
                          axisLine={false}
                          tickLine={false}
                          tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                          minTickGap={32}
                        />
                        <YAxis
                          axisLine={false}
                          tickLine={false}
                          width={36}
                          tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                        />
                        <Tooltip
                          content={({ active, payload, label }) =>
                            active && payload && payload.length ? (
                              <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
                                <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                                  {label}
                                </div>
                                <div className="mt-1 font-mono text-sm">
                                  {String(payload[0].value)} {m.label.toLowerCase()}
                                </div>
                              </div>
                            ) : null
                          }
                        />
                        <Area
                          type="monotone"
                          dataKey="value"
                          stroke="hsl(var(--accent))"
                          strokeWidth={2}
                          fill={`url(#grad-${m.key})`}
                          isAnimationActive={false}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </TabsContent>
            );
          })}
        </Tabs>
      </CardContent>
    </Card>
  );
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex h-[220px] items-center justify-center rounded-md border border-dashed text-sm italic text-muted-foreground">
      {message}
    </div>
  );
}
