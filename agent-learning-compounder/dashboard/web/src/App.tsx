import { useCallback, useEffect, useState } from "react";
import { readDashboardData, type DashboardData } from "@/lib/data";
import { KpiCards } from "@/components/KpiCards";
import { TrendChart } from "@/components/TrendChart";
import { DomainHeat } from "@/components/DomainHeat";
import { GateStabilityTable } from "@/components/GateStabilityTable";
import { SkillPanel } from "@/components/SkillPanel";
import { RunHistory } from "@/components/RunHistory";
import { ActionBar } from "@/components/ActionBar";
import { ToastHost } from "@/components/StatusToast";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { useConnection, apiGet } from "@/hooks/useConnection";

function applyStoredTheme() {
  if (typeof document === "undefined") return;
  try {
    const stored = localStorage.getItem("alc-theme");
    if (stored === "light") document.documentElement.classList.remove("dark");
    if (stored === "dark") document.documentElement.classList.add("dark");
  } catch {
    /* noop */
  }
}

export default function App() {
  applyStoredTheme();
  const [data, setData] = useState<DashboardData>(() => readDashboardData());
  const connection = useConnection();

  const refreshData = useCallback(async () => {
    if (!connection.online) {
      setData(readDashboardData());
      return;
    }
    try {
      const live = await apiGet<DashboardData>("/api/data");
      setData(live);
    } catch {
      setData(readDashboardData());
    }
  }, [connection.online]);

  // First load when API comes online, refresh data.
  useEffect(() => {
    refreshData();
  }, [refreshData]);

  // Lightweight auto-refresh when connected (every 25s).
  useEffect(() => {
    if (!connection.online) return;
    const id = setInterval(refreshData, 25_000);
    return () => clearInterval(id);
  }, [connection.online, refreshData]);

  const latest = data.latest;
  const runs = data.history.length;
  const hasData = latest != null || runs > 0;

  return (
    <div className="min-h-screen bg-background">
      <ToastHost />
      <div className="container max-w-[1280px] py-8">
        {/* Header */}
        <header className="mb-8 flex flex-wrap items-end justify-between gap-6">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.22em] text-muted-foreground">
              <span className="inline-block h-2 w-2 rounded-full bg-accent" />
              Agent Learning · Dashboard
            </div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">
              {latest?.repo && latest.repo !== "unknown" && latest.repo !== "None" ? (
                <>
                  <span className="text-muted-foreground">repo</span>{" "}
                  <span>{latest.repo}</span>
                </>
              ) : (
                <>Tracking &amp; metrics</>
              )}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {hasData ? (
                <>
                  {runs} run{runs === 1 ? "" : "s"} on record · latest filed{" "}
                  <span className="font-mono text-foreground">{latest?.date ?? "—"}</span>
                  {latest?.mode && (
                    <span className="ml-1">
                      · mode <code>{latest.mode}</code>
                    </span>
                  )}
                </>
              ) : (
                "No runs recorded yet. Run distill --write to populate this dashboard."
              )}
            </p>
          </div>
          <ActionBar data={data} connection={connection} onDataRefresh={refreshData} />
        </header>

        {/* KPI strip */}
        <KpiCards data={data} />

        <Separator className="my-8" />

        {/* Tracking + heat */}
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <TrendChart data={data} />
          <DomainHeat data={data} />
        </section>

        <Separator className="my-8" />

        {/* Gate stability + run history */}
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
          <GateStabilityTable data={data} online={connection.online} onChange={refreshData} />
          <RunHistory data={data} />
        </section>

        <Separator className="my-8" />

        {/* Skill telemetry */}
        <SkillPanel data={data} />

        {/* Footer */}
        <footer className="mt-12 flex flex-wrap items-center justify-between gap-3 text-[11px] text-muted-foreground">
          <div className="flex items-center gap-3">
            <Badge variant="outline">generated {data.generated_at}</Badge>
            <span>
              personal root: <code>{data.personal_root}</code>
            </span>
          </div>
          <span className="font-mono">agent-learning-compounder · self-contained · offline-safe</span>
        </footer>
      </div>
    </div>
  );
}
