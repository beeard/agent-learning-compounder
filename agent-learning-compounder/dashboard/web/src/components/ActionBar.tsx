import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { DashboardData } from "@/lib/data";
import { apiPost } from "@/hooks/useConnection";
import { pushToast } from "@/components/StatusToast";
import type { ConnectionState } from "@/hooks/useConnection";
import { RefreshCw, Copy, Download, Moon, Sun, Loader2, ExternalLink, FileText } from "lucide-react";

interface Props {
  data: DashboardData;
  connection: ConnectionState & { refresh: () => Promise<void> };
  onDataRefresh: () => Promise<void>;
}

export function ActionBar({ data, connection, onDataRefresh }: Props) {
  const [busy, setBusy] = useState(false);
  const online = connection.online;

  const distill = async () => {
    setBusy(true);
    try {
      const res = await apiPost<{ job_id: string; status: string }>("/api/actions/distill");
      pushToast("ok", `distill queued · job ${res.job_id}`);
      // The distill subprocess is detached; poll briefly for new metrics.
      setTimeout(async () => {
        try {
          await onDataRefresh();
          pushToast("ok", "metrics refreshed");
        } catch {
          /* ignore */
        }
      }, 6000);
    } catch (err: any) {
      pushToast("error", `distill failed · ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  const copyCommand = async () => {
    const cmd =
      "python3 ~/.claude/skills/agent-learning-compounder/scripts/distill_learning.py --write --personal ~/.agent-learning";
    try {
      await navigator.clipboard.writeText(cmd);
      pushToast("ok", "command copied");
    } catch {
      pushToast("error", "clipboard blocked");
    }
  };

  const copyPayload = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      pushToast("ok", "payload copied");
    } catch {
      pushToast("error", "clipboard blocked");
    }
  };

  const toggleTheme = () => {
    const root = document.documentElement;
    const isDark = root.classList.toggle("dark");
    try {
      localStorage.setItem("alc-theme", isDark ? "dark" : "light");
    } catch {
      /* noop */
    }
  };

  const openReport = () => {
    if (online) {
      window.open("/api/reports/latest", "_blank", "noopener");
    } else {
      pushToast("info", "open ~/.agent-learning/reports/agent-learning/latest-report.html");
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <ConnectionBadge connection={connection} />
      <div className="flex-1" />
      <Button
        size="sm"
        variant={online ? "accent" : "outline"}
        disabled={!online || busy}
        onClick={distill}
        title={online ? "Run distill --write now" : "start serve_dashboard.py to enable"}
      >
        {busy ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
        ) : (
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
        )}
        Re-run distill
      </Button>
      <Button size="sm" variant="outline" onClick={openReport} title="Open latest .md/.html report">
        <FileText className="mr-1.5 h-3.5 w-3.5" />
        Latest report
      </Button>
      <Button size="sm" variant="outline" onClick={copyCommand} title="Copy the distill command to clipboard">
        <Copy className="mr-1.5 h-3.5 w-3.5" />
        Copy command
      </Button>
      <Button size="sm" variant="ghost" onClick={copyPayload} title="Copy the embedded payload JSON">
        <Download className="mr-1.5 h-3.5 w-3.5" />
        Payload
      </Button>
      <Button size="icon" variant="ghost" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
        <Moon className="hidden h-4 w-4 dark:block" />
        <Sun className="block h-4 w-4 dark:hidden" />
      </Button>
    </div>
  );
}

function ConnectionBadge({
  connection,
}: {
  connection: ConnectionState & { refresh: () => Promise<void> };
}) {
  if (connection.online) {
    return (
      <Badge
        variant="high"
        title={`API up · ${connection.personal ?? ""}`}
        className="cursor-default"
      >
        <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-background" />
        Connected
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className="cursor-help"
      title={connection.error ?? "API unreachable. Run: python3 scripts/serve_dashboard.py"}
      onClick={() => connection.refresh()}
    >
      <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/60" />
      Offline · static
      <ExternalLink className="ml-1.5 h-2.5 w-2.5 opacity-60" />
    </Badge>
  );
}
