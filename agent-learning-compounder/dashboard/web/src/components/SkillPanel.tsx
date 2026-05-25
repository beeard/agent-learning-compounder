import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DashboardData } from "@/lib/data";

export function SkillPanel({ data }: { data: DashboardData }) {
  const latest = data.latest;
  const inv = latest?.skill_inventory;
  const usage = latest?.skill_usage;
  const health = latest?.skill_health;
  const comp = latest?.skill_compensation?.rows ?? [];
  const empty =
    (!inv || (inv.available_count === 0 && (inv.rows?.length ?? 0) === 0)) &&
    (!usage || ((usage.expected?.length ?? 0) === 0 && (usage.loaded?.length ?? 0) === 0)) &&
    (!health || (!health.invalid?.length && !health.missed?.length && !health.failed_to_apply?.length));

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Skill telemetry</CardTitle>
        <p className="mt-1 text-xs italic text-muted-foreground">
          Which tools the agent had, used, missed. Populates once you pass --skill-map / --skill-usage / --skill-impact JSON.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {empty ? (
          <div className="rounded-md border border-dashed p-4 text-sm italic text-muted-foreground">
            — No skill telemetry in this filing. Feed in skill-map JSON from <code>map_active_skills.py</code> to populate.
          </div>
        ) : (
          <>
            <SkillRow label="Available" values={inv?.rows.map((r) => r.name) ?? []} total={inv?.available_count ?? 0} variant="default" />
            <SkillRow label="Expected" values={usage?.expected ?? []} variant="accent" />
            <SkillRow label="Loaded" values={usage?.loaded ?? []} variant="secondary" />
            <SkillRow label="Applied" values={usage?.applied ?? []} variant="high" />
            <SkillRow label="Invalid" values={health?.invalid ?? []} variant="destructive" />
            <SkillRow label="Missed" values={health?.missed ?? []} variant="mid" />
            <SkillRow label="Loaded · not applied" values={health?.failed_to_apply ?? []} variant="low" />
            {comp.length > 0 && (
              <div className="rounded-md border border-border bg-muted/30 p-3">
                <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                  Compensation candidates
                </div>
                <ul className="mt-2 space-y-2 text-sm">
                  {comp.map((c, i) => (
                    <li key={`${c.skill}-${i}`} className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="accent">{c.skill}</Badge>
                        <span className="text-xs text-muted-foreground">
                          {c.signal} · {c.count} sessions
                        </span>
                      </div>
                      <div className="text-xs text-foreground">{c.gate}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function SkillRow({
  label,
  values,
  total,
  variant = "default",
}: {
  label: string;
  values: string[];
  total?: number;
  variant?: "default" | "accent" | "secondary" | "high" | "mid" | "low" | "destructive";
}) {
  const count = total ?? values.length;
  if (count === 0) return null;
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
      <div className="w-40 shrink-0">
        <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
        <div className="font-mono text-lg tabular-nums text-foreground">{count}</div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {values.slice(0, 24).map((v) => (
          <Badge key={v} variant={variant}>
            {v}
          </Badge>
        ))}
        {values.length > 24 && (
          <span className="text-[11px] text-muted-foreground">+{values.length - 24} more</span>
        )}
      </div>
    </div>
  );
}
