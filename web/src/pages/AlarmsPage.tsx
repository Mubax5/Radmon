import { useEffect, useState } from "react";
import { Button } from "@cloudflare/kumo";
import { api } from "../api";
import { AlarmOperations } from "../Actions";
import { useWebRefresh } from "../live";
import { ErrorCard, JsonTable, LoadingCard, PageHeading } from "../ui";

export type PolicyEvent = Record<string, unknown> & {
  event_id: string;
  serid: number;
  status: string;
  kind: string;
  measured_value?: number | null;
  threshold?: number | null;
  surfaced_at?: string;
};

export function AlarmsPage() {
  const [items, setItems] = useState<PolicyEvent[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api<PolicyEvent[]>("/api/v1/control/alarm-events")
    .then((rows) => {
      setItems(rows);
      setError("");
    })
    .catch((e) => setError(e instanceof Error ? e.message : "Unable to load alarms"));

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); }, ["live_update"]);

  return (
    <>
      <PageHeading
        title="Alarms"
        description="Central alarm-policy events. Response and suppression are protected by operator role and PIN policy."
        action={<Button variant="secondary" onClick={() => void load()}>Refresh</Button>}
      />
      {error ? <ErrorCard message={error} /> : null}
      {items ? (
        <>
          <AlarmOperations events={items} onChanged={() => void load()} />
          <JsonTable rows={items} empty="No alarm events." />
        </>
      ) : <LoadingCard />}
    </>
  );
}
