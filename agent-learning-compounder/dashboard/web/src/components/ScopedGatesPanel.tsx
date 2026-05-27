import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { DashboardData, ScopedGateRow } from "@/lib/data";

interface Props {
  data: DashboardData;
}

function GatesList({ rows, emptyHint }: { rows: ScopedGateRow[]; emptyHint: string }) {
  if (rows.length === 0) {
    return <p className="text-sm italic text-muted-foreground">{emptyHint}</p>;
  }
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li key={row.gate_id} className="rounded-md border border-border/60 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="accent">{row.domain}</Badge>
            <Badge variant="outline">{row.category}</Badge>
            <code className="ml-auto text-[10px] text-muted-foreground">{row.gate_id}</code>
          </div>
          <p className="mt-2 text-sm leading-snug">{row.gate}</p>
        </li>
      ))}
    </ul>
  );
}

export function ScopedGatesPanel({ data }: Props) {
  const scoped = data.scoped_gates;
  if (!scoped) return null;
  const { rows, summary } = scoped;
  const userRows = rows.filter((row) => row._source_scope === "user");
  const projectRows = rows.filter((row) => row._source_scope === "project");

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm font-medium">Approved gates</CardTitle>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <Badge variant="outline">{summary.total} total</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="project">
          <TabsList>
            <TabsTrigger value="project">
              This project
              <Badge variant="outline" className="ml-2">
                {summary.project}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="user">
              Across all your work
              <Badge variant="outline" className="ml-2">
                {summary.user}
              </Badge>
            </TabsTrigger>
          </TabsList>
          <TabsContent value="project">
            <GatesList
              rows={projectRows}
              emptyHint="No project-scope gates yet. Run distill --write to populate."
            />
          </TabsContent>
          <TabsContent value="user">
            <GatesList
              rows={userRows}
              emptyHint="No user-scope gates yet. Auto-distill accumulates these across sessions."
            />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
