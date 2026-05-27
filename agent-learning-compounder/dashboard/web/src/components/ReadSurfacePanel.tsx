import { Activity, FileJson, GitPullRequestArrow, Lightbulb, Puzzle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { DashboardData } from "@/lib/data";
import { formatNum, relTime } from "@/lib/utils";

function textValue(row: Record<string, unknown>, keys: string[], fallback = "—") {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return fallback;
}

function EmptyRow({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed p-4 text-sm italic text-muted-foreground">
      {label}
    </div>
  );
}

function EventList({ rows, empty }: { rows: Record<string, unknown>[]; empty: string }) {
  if (rows.length === 0) return <EmptyRow label={empty} />;
  return (
    <ul className="space-y-2">
      {rows.map((row, index) => {
        const event = textValue(row, ["event", "kind", "type"]);
        const ts = textValue(row, ["ts", "created_at", "updated_at"], "");
        const actor = textValue(row, ["actor_name", "actor_kind", "by"], "");
        return (
          <li
            key={`${event}-${ts}-${index}`}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border/60 bg-secondary/30 px-3 py-2.5"
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{event}</Badge>
                {actor ? <span className="text-xs text-muted-foreground">{actor}</span> : null}
              </div>
              <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                {textValue(row, ["event_id", "patch_id", "id"], "no id")}
              </div>
            </div>
            <span className="font-mono text-[11px] text-muted-foreground">{ts ? relTime(ts) : "—"}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function ReadSurfacePanel({ data }: { data: DashboardData }) {
  const surface = data.read_surface;
  if (!surface) return null;

  const actors = surface.actor_summary.by_actor_kind ?? [];
  const diagnostics = surface.diagnostics;
  const coldReasons = diagnostics.cold_state_reasons ?? [];
  const sqliteWarm = diagnostics.events_sqlite_present && diagnostics.events_sqlite_bytes > 0;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div>
          <CardTitle className="text-sm font-medium">Canonical read surface</CardTitle>
          <p className="mt-1 text-xs italic text-muted-foreground">
            Repo-scope signals from alc_query, refreshed through the FastAPI shell.
          </p>
        </div>
        <Badge variant={sqliteWarm ? "accent" : "outline"}>
          {sqliteWarm ? "indexed" : "cold index"}
        </Badge>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="overview">
          <TabsList className="flex h-auto flex-wrap justify-start">
            <TabsTrigger value="overview">
              <Activity className="mr-1.5 h-3.5 w-3.5" />
              Activity
            </TabsTrigger>
            <TabsTrigger value="recommendations">
              <Lightbulb className="mr-1.5 h-3.5 w-3.5" />
              Recommendations
              <Badge variant="outline" className="ml-2">
                {surface.recommendations.length}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="patches">
              <GitPullRequestArrow className="mr-1.5 h-3.5 w-3.5" />
              Patches
              <Badge variant="outline" className="ml-2">
                {surface.pending_patches.length}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="skills">
              <Puzzle className="mr-1.5 h-3.5 w-3.5" />
              Skills
              <Badge variant="outline" className="ml-2">
                {surface.skill_usage.length}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="suggestions">
              <Lightbulb className="mr-1.5 h-3.5 w-3.5" />
              Suggestions
              <Badge variant="outline" className="ml-2">
                {surface.suggestions.length}
              </Badge>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
              <div className="rounded-md border border-border/60 p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                      Actor events
                    </div>
                    <div className="mt-1 text-3xl font-semibold tabular-nums">
                      {formatNum(surface.actor_summary.total)}
                    </div>
                  </div>
                  <Badge variant="secondary">since {surface.actor_summary.since}</Badge>
                </div>
                {actors.length === 0 ? (
                  <p className="mt-4 text-sm italic text-muted-foreground">
                    No indexed actor events in this window.
                  </p>
                ) : (
                  <ul className="mt-4 space-y-2">
                    {actors.map((row) => (
                      <li key={row.actor_kind} className="flex items-center justify-between gap-3 text-sm">
                        <span className="font-mono">{row.actor_kind || "(unknown)"}</span>
                        <span className="text-muted-foreground">
                          {formatNum(row.count)} events · {formatNum(row.unique_actors)} actors
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="rounded-md border border-border/60 p-4">
                <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                  <FileJson className="h-3.5 w-3.5" />
                  Index files
                </div>
                <dl className="grid gap-2 text-sm">
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-muted-foreground">events.sqlite</dt>
                    <dd className="font-mono">{formatNum(diagnostics.events_sqlite_bytes)} B</dd>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-muted-foreground">events.jsonl</dt>
                    <dd className="font-mono">{formatNum(diagnostics.events_jsonl_bytes)} B</dd>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <dt className="text-muted-foreground">hook-events.jsonl</dt>
                    <dd className="font-mono">{formatNum(diagnostics.hook_events_bytes)} B</dd>
                  </div>
                </dl>
                <p className="mt-3 truncate font-mono text-[11px] text-muted-foreground">
                  {diagnostics.repo_state}
                </p>
                {coldReasons.length > 0 ? (
                  <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
                    {coldReasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="recommendations">
            <EventList rows={surface.recommendations} empty="No recommendations recorded." />
          </TabsContent>

          <TabsContent value="patches">
            <EventList rows={surface.pending_patches} empty="No pending patch bundles." />
          </TabsContent>

          <TabsContent value="skills">
            {surface.skill_usage.length === 0 ? (
              <EmptyRow label="No indexed skill usage in the last 30 days." />
            ) : (
              <ul className="space-y-2">
                {surface.skill_usage.map((row) => (
                  <li
                    key={row.actor_name}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border/60 bg-secondary/30 px-3 py-2.5"
                  >
                    <span className="font-mono text-xs">{row.actor_name}</span>
                    <span className="text-xs text-muted-foreground">
                      {formatNum(row.count)} events · last {relTime(row.last_used_ts)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>

          <TabsContent value="suggestions">
            <EventList rows={surface.suggestions} empty="No workflow suggestions recorded." />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
