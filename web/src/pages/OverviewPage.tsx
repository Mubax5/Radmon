import { useEffect, useMemo, useState } from "react";
import { Badge, LayerCard } from "@cloudflare/kumo";
import { api, type Station } from "../api";
import { useSession } from "../auth";
import { AlarmNotification, hasActiveThresholdEvent } from "../components/AlarmStatus";
import { useWebRefresh } from "../live";
import { navigate } from "../navigation";
import {
  ErrorCard,
  LoadingCard,
  MetricCard,
  PageHeading,
  PageSection,
  ResponsiveStationView,
  formatTimestamp,
  freshnessLabel,
} from "../ui";

type Overview = {
  counts: Record<string, number>;
  stations: Station[];
};

const SEVERITY: Record<string, number> = { alarm: 0, warning: 1, offline: 2, normal: 3 };

export function OverviewPage() {
  const { user } = useSession();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const load = () => api<Overview>("/api/v1/web/overview")
    .then((value) => { setData(value); setError(""); })
    .catch((e) => setError(e instanceof Error ? e.message : "Tidak dapat memuat ringkasan monitoring"));

  useEffect(() => { void load(); }, []);
  useWebRefresh(load);

  const derived = useMemo(() => {
    if (!data) return { attention: [] as Station[], latest: null as string | null };
    const attention = data.stations
      .filter((station) => station.status !== "normal")
      .sort((a, b) => (SEVERITY[a.status ?? "offline"] ?? 9) - (SEVERITY[b.status ?? "offline"] ?? 9));
    const timestamps = data.stations
      .map((station) => station.dtom ? Date.parse(station.dtom) : Number.NaN)
      .filter(Number.isFinite);
    const latest = timestamps.length ? new Date(Math.max(...timestamps)).toISOString() : null;
    return { attention, latest };
  }, [data]);

  if (!data && !error) return <LoadingCard />;

  const countValue = (key: string): number | "—" => {
    const value = data?.counts?.[key];
    return typeof value === "number" && Number.isFinite(value) ? value : "—";
  };

  const cards = data ? [
    ["Normal", countValue("normal"), "success"],
    ["Peringatan", countValue("warning"), "warning"],
    ["Alarm", countValue("alarm"), "error"],
    ["Offline", countValue("offline"), "secondary"],
  ] as const : [];
  const openAlarm = user && user.role !== "Viewer"
    ? (station: Station) => navigate("alarms", { serid: station.serid, event: station.active_event_id ?? undefined })
    : undefined;

  return (
    <div className="page-stack">
      <PageHeading
        title="Monitoring radiasi"
        description="Pantau kondisi radiasi terkini dan temukan stasiun yang perlu diperiksa."
      />
      {error ? <ErrorCard message={error} /> : null}
      {data ? (
        <>
          <div className="alarm-notification-stack" aria-live="off">
            {data.stations.filter(hasActiveThresholdEvent)
              .map((station) => <AlarmNotification key={station.active_event_id} station={station} onAction={openAlarm} />)}
          </div>
          <div className="metric-grid">
            {cards.map(([label, value, variant]) => (
              <MetricCard key={label} label={label} value={value} badge={<Badge variant={variant}>{label}</Badge>} />
            ))}
          </div>

          <PageSection
            title="Perhatian"
            description="Stasiun alarm, peringatan, dan offline ditampilkan lebih dulu agar mudah ditindaklanjuti."
            className="attention-panel"
          >
            {derived.attention.length ? (
              <ResponsiveStationView
                stations={derived.attention}
                onHistory={(station) => navigate("history", { station: station.serid })}
                onAlarm={openAlarm}
              />
            ) : (
              <LayerCard className="empty-card">Tidak ada stasiun yang saat ini memerlukan perhatian operator.</LayerCard>
            )}
          </PageSection>

          <PageSection title="Kesegaran data" description="Waktu pembaruan terakhir dari seluruh stasiun.">
            <div className="metric-grid freshness-grid">
              <MetricCard
                label="Measurement live terbaru"
                value={derived.latest ? freshnessLabel(derived.latest) : "Belum ada data"}
                badge={<span className="cell-subtle">{formatTimestamp(derived.latest)}</span>}
              />
              <MetricCard
                label="Stasiun terkonfigurasi"
                value={data.stations.length}
                badge={<span className="cell-subtle">Dalam pemantauan</span>}
              />
            </div>
          </PageSection>

          <PageSection title="Kesehatan stasiun" description="Dose, status, dan waktu update terbaru untuk setiap stasiun.">
            <ResponsiveStationView
              stations={data.stations}
              onHistory={(station) => navigate("history", { station: station.serid })}
              onAlarm={openAlarm}
            />
          </PageSection>
        </>
      ) : null}
    </div>
  );
}
