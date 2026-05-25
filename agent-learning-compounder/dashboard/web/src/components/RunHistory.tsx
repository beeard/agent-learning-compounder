import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DashboardData } from "@/lib/data";
import { Badge } from "@/components/ui/badge";
import { relTime } from "@/lib/utils";

export function RunHistory({ data }: { data: DashboardData }) {
  const rows = [...data.history].reverse().slice(0, 12);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Recent runs</CardTitle>
        <p className="mt-1 text-xs italic text-muted-foreground">
          Last {rows.length} --write invocations. Newest first.
        </p>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <div className="rounded-md border border-dashed p-4 text-sm italic text-muted-foreground">
            No runs recorded yet.
          </div>
        ) : (
          <ul className="space-y-2">
            {rows.map((r, i) => {
              const top = (r.by_domain ?? [])[0];
              return (
                <li
                  key={`${r.ts}-${i}`}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 bg-secondary/30 px-3 py-2.5"
                >
                  <div className="flex flex-col">
                    <span className="font-mono text-xs text-foreground">{r.ts}</span>
                    <span className="text-[11px] text-muted-foreground">{relTime(r.ts)}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <Badge variant="outline">{r.totals.gates} rules</Badge>
                    <Badge variant="secondary">{r.totals.evidence_lines} ev</Badge>
                    {top && (
                      <span className="text-muted-foreground">
                        top: <span className="font-mono text-foreground">{top.domain}</span>
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
