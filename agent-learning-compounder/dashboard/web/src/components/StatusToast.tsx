import { useEffect, useState } from "react";

export interface ToastMessage {
  id: number;
  kind: "ok" | "error" | "info";
  text: string;
}

let _toastId = 0;
const listeners: Array<(t: ToastMessage) => void> = [];

export function pushToast(kind: ToastMessage["kind"], text: string) {
  const msg: ToastMessage = { id: ++_toastId, kind, text };
  for (const l of listeners) l(msg);
}

export function ToastHost() {
  const [items, setItems] = useState<ToastMessage[]>([]);
  useEffect(() => {
    const handler = (msg: ToastMessage) => {
      setItems((cur) => [...cur, msg]);
      setTimeout(() => setItems((cur) => cur.filter((m) => m.id !== msg.id)), 4500);
    };
    listeners.push(handler);
    return () => {
      const i = listeners.indexOf(handler);
      if (i >= 0) listeners.splice(i, 1);
    };
  }, []);
  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-50 flex flex-col gap-2">
      {items.map((m) => (
        <div
          key={m.id}
          className={`pointer-events-auto rounded-md border bg-card px-3 py-2 font-mono text-xs shadow-md ${
            m.kind === "error"
              ? "border-destructive/40 text-destructive"
              : m.kind === "ok"
                ? "border-accent/40 text-accent"
                : "border-border text-foreground"
          }`}
        >
          {m.text}
        </div>
      ))}
    </div>
  );
}
