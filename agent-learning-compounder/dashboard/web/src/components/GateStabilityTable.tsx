import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DashboardData } from "@/lib/data";
import { gateStability, levelLabel } from "@/lib/data";
import { relTime } from "@/lib/utils";
import { apiPost } from "@/hooks/useConnection";
import { pushToast } from "@/components/StatusToast";
import { Check, VolumeX, Star, Volume2, StarOff } from "lucide-react";

interface Props {
  data: DashboardData;
  online: boolean;
  onChange: () => Promise<void>;
}

interface ActionsState {
  promoted: { key: string }[];
  muted: { domain: string }[];
}

export function GateStabilityTable({ data, online, onChange }: Props) {
  const rows = gateStability(data.history);
  const actions: ActionsState = (data as any).actions ?? { promoted: [], muted: [] };
  const promotedKeys = new Set(actions.promoted.map((p) => p.key));
  const mutedDomains = new Set(actions.muted.map((m) => m.domain));
  const [pending, setPending] = useState<Record<string, "promote" | "mute" | null>>({});

  const setPendingFor = (key: string, value: "promote" | "mute" | null) =>
    setPending((s) => ({ ...s, [key]: value }));

  const promote = async (row: ReturnType<typeof gateStability>[number]) => {
    setPendingFor(row.key, "promote");
    try {
      if (promotedKeys.has(row.key)) {
        await apiPost("/api/actions/unpromote", { key: row.key });
        pushToast("info", `unpromoted ${row.domain}`);
      } else {
        await apiPost("/api/actions/promote", {
          key: row.key,
          domain: row.domain,
          gate_category: row.gate_category,
        });
        pushToast("ok", `promoted ${row.domain}`);
      }
      await onChange();
    } catch (err: any) {
      pushToast("error", err.message);
    } finally {
      setPendingFor(row.key, null);
    }
  };

  const mute = async (row: ReturnType<typeof gateStability>[number]) => {
    setPendingFor(row.key, "mute");
    try {
      if (mutedDomains.has(row.domain)) {
        await apiPost("/api/actions/unmute", { domain: row.domain });
        pushToast("info", `unmuted ${row.domain}`);
      } else {
        await apiPost("/api/actions/mute", {
          domain: row.domain,
          reason: "from-dashboard",
        });
        pushToast("ok", `muted ${row.domain} · skipped on next distill`);
      }
      await onChange();
    } catch (err: any) {
      pushToast("error", err.message);
    } finally {
      setPendingFor(row.key, null);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Gate stability</CardTitle>
        <p className="mt-1 text-xs italic text-muted-foreground">
          Which rules keep appearing across runs (durable) vs. which are transient noise.
          {online ? " Promote a gate to mark it durable. Mute a domain to skip it on the next --write run." : null}
        </p>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <div className="rounded-md border border-dashed p-6 text-center text-sm italic text-muted-foreground">
            No history yet — first --write run will start populating stability.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  <th className="border-b border-border py-2 text-left font-medium">Domain · Category</th>
                  <th className="border-b border-border py-2 text-left font-medium">Best level</th>
                  <th className="border-b border-border py-2 text-right font-medium">Runs</th>
                  <th className="border-b border-border py-2 text-right font-medium">Stability</th>
                  <th className="border-b border-border py-2 text-right font-medium">Last seen</th>
                  <th className="border-b border-border py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const lvl = levelLabel(row.best_level);
                  const pct = Math.round(row.stability * 100);
                  const promoted = promotedKeys.has(row.key);
                  const muted = mutedDomains.has(row.domain);
                  const isPending = pending[row.key];
                  return (
                    <tr
                      key={row.key}
                      className={`border-b border-border/60 last:border-b-0 ${
                        muted ? "opacity-50" : ""
                      } hover:bg-muted/40`}
                    >
                      <td className="py-3 align-middle">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[12px] uppercase tracking-wider text-foreground">
                            {row.domain}
                          </span>
                          {promoted && (
                            <Badge variant="accent" className="text-[9px]">
                              <Check className="mr-1 h-2.5 w-2.5" />
                              Promoted
                            </Badge>
                          )}
                          {muted && (
                            <Badge variant="outline" className="text-[9px] text-muted-foreground">
                              <VolumeX className="mr-1 h-2.5 w-2.5" />
                              Muted
                            </Badge>
                          )}
                        </div>
                        <div className="text-[11px] text-muted-foreground">
                          <code className="bg-transparent p-0">{row.gate_category}</code>
                        </div>
                      </td>
                      <td className="py-3 align-middle">
                        <Badge variant={lvl.tone}>{lvl.label}</Badge>
                      </td>
                      <td className="py-3 text-right font-mono tabular-nums">
                        {row.runs}
                        <span className="text-muted-foreground">/{row.total_runs}</span>
                      </td>
                      <td className="py-3 align-middle">
                        <div className="ml-auto flex w-32 items-center gap-2">
                          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full rounded-full bg-accent"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                            {pct}%
                          </span>
                        </div>
                      </td>
                      <td className="py-3 text-right text-xs text-muted-foreground">
                        {relTime(row.last_seen)}
                      </td>
                      <td className="py-3 text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            variant={promoted ? "accent" : "ghost"}
                            disabled={!online || isPending === "promote"}
                            onClick={() => promote(row)}
                            title={
                              !online
                                ? "Connect to API to enable"
                                : promoted
                                  ? "Remove promotion"
                                  : "Mark as durable rule"
                            }
                          >
                            {promoted ? (
                              <StarOff className="mr-1 h-3 w-3" />
                            ) : (
                              <Star className="mr-1 h-3 w-3" />
                            )}
                            {promoted ? "Unpromote" : "Promote"}
                          </Button>
                          <Button
                            size="sm"
                            variant={muted ? "outline" : "ghost"}
                            disabled={!online || isPending === "mute"}
                            onClick={() => mute(row)}
                            title={
                              !online
                                ? "Connect to API to enable"
                                : muted
                                  ? "Restore this domain"
                                  : "Suppress on next --write run"
                            }
                          >
                            {muted ? (
                              <Volume2 className="mr-1 h-3 w-3" />
                            ) : (
                              <VolumeX className="mr-1 h-3 w-3" />
                            )}
                            {muted ? "Unmute" : "Mute"}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
