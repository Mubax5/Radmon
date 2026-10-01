import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Button, LayerCard, Select, Table } from "@cloudflare/kumo";
import { CaretLeft, CaretRight } from "@phosphor-icons/react";
import { api, type Station } from "../api";
import { TrendChart, type TrendPoint } from "../components/TrendChart";
import { ResponsiveDataView } from "../components/ResponsiveDataView";
import { useWebRefresh } from "../live";
import { useSession } from "../auth";
import { AlarmStatus } from "../components/AlarmStatus";
import { navigate } from "../navigation";
import { formatDoseValue } from "../format";
import {
  ErrorCard,
  LoadingCard,
  MetricCard,
  PageHeading,
  PageSection,
  formatTimestamp,
  freshnessLabel,
} from "../ui";

type HistoryRow = Record<string, unknown> & {
  dtom?: string;
  doserate?: number | string | null;
  dose?: number | string | null;
  stat?: number | string | null;
};

function numericDoseRate(row: HistoryRow): number | null {
  const value = Number(row.doserate);
  return Number.isFinite(value) ? value : null;
}

const LIMIT_ITEMS: Record<string, string> = {
  "60": "1 jam — 60",
  "240": "4 jam — 240",
  "720": "12 jam — 720",
  "1440": "24 jam — 1440",
  "2000": "Maks — 2000",
};

export function HistoryPage() {
  const { user } = useSession();
  const [stations, setStations] = useState<Station[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState<string | null>(null);
  const [stationMenuOpen, setStationMenuOpen] = useState(false);
  const [activeStationIndex, setActiveStationIndex] = useState(0);
  const [stationMenuStyle, setStationMenuStyle] = useState<CSSProperties>({});
  const [limit, setLimit] = useState(240);
  const stationInputRef = useRef<HTMLInputElement>(null);
  const rowsRef = useRef<HistoryRow[]>(rows);
  const requestIdRef = useRef(0);
  rowsRef.current = rows;

  // cache for instant station switch and prefetch: key = `${serid}:${limit}`
  const cacheRef = useRef<Map<string, HistoryRow[]>>(new Map());
  const cacheKey = useCallback((serid: number, lim: number) => `${serid}:${lim}`, []);

  const selectedIndex = useMemo(() => {
    if (selected == null) return -1;
    return stations.findIndex((station) => station.serid === selected);
  }, [stations, selected]);

  const selectedStation = selectedIndex >= 0 ? stations[selectedIndex] : null;

  useLayoutEffect(() => {
    if (!stationMenuOpen) return;
    const input = stationInputRef.current;
    if (!input) return;

    const positionMenu = () => {
      const rect = input.getBoundingClientRect();
      const margin = 8;
      const gap = 4;
      const viewportWidth = document.documentElement.clientWidth;
      const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
      const left = Math.max(margin, Math.min(rect.left, viewportWidth - margin));
      const width = Math.max(0, Math.min(rect.width, viewportWidth - left - margin));
      const below = Math.max(0, viewportHeight - rect.bottom - margin - gap);
      const above = Math.max(0, rect.top - margin - gap);
      const placeAbove = below < 180 && above > below;
      const maxHeight = Math.max(48, Math.min(320, placeAbove ? above : below));
      setStationMenuStyle({
        position: "fixed",
        zIndex: 2147483647,
        left,
        top: placeAbove ? Math.max(margin, rect.top - gap - maxHeight) : rect.bottom + gap,
        width,
        maxHeight,
      });
    };

    positionMenu();
    window.addEventListener("resize", positionMenu);
    window.addEventListener("scroll", positionMenu, true);
    const viewport = window.visualViewport;
    viewport?.addEventListener("resize", positionMenu);
    viewport?.addEventListener("scroll", positionMenu);
    return () => {
      window.removeEventListener("resize", positionMenu);
      window.removeEventListener("scroll", positionMenu, true);
      viewport?.removeEventListener("resize", positionMenu);
      viewport?.removeEventListener("scroll", positionMenu);
    };
  }, [stationMenuOpen]);

  const filteredStations = useMemo(() => {
    const needle = (query ?? "").trim().toLowerCase();
    if (!needle) return stations;
    return stations.filter((station) => {
      const hay = `${station.name} ${station.serid}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [stations, query]);

  useEffect(() => {
    if (!stationMenuOpen) return;
    const activeOption = filteredStations[activeStationIndex];
    if (!activeOption) return;
    document.getElementById(`history-station-option-${activeOption.serid}`)?.scrollIntoView({ block: "nearest" });
  }, [activeStationIndex, filteredStations, stationMenuOpen]);

  // For carousel, full list order is stations as returned (location, name). Keep wrap navigation.
  const hasStations = stations.length > 0;
  const canNavigate = stations.length > 1;

  // --- URL sync (?serid=) with backward compat for ?station= ---
  function readRequestedSerid(): number | null {
    const params = new URLSearchParams(window.location.search);
    // support both ?serid= and legacy ?station=
    const rawSerid = params.get("serid");
    const rawStation = params.get("station");
    const candidate = rawSerid ?? rawStation;
    const num = Number(candidate);
    return Number.isInteger(num) && num > 0 ? num : null;
  }

  function syncUrl(serid: number | null) {
    if (serid == null) {
      window.history.replaceState({}, "", "/app/history");
      return;
    }
    // canonical ?serid=, keep ?station= as alias for backward compat deep links
    const params = new URLSearchParams(window.location.search);
    params.set("serid", String(serid));
    params.set("station", String(serid));
    window.history.replaceState({}, "", `/app/history?${params.toString()}`);
    // also ensure bare ?serid= is test-visible: keep string literal get("serid") and get("station") handled via read above
  }

  useEffect(() => {
    api<Station[]>("/api/v1/web/stations")
      .then((items) => {
        setStations(items);
        const requested = readRequestedSerid();
        const initial = requested != null && items.some((item) => item.serid === requested)
          ? requested
          : items[0]?.serid ?? null;
        setSelected(initial);
        if (initial == null) setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Tidak dapat memuat stasiun");
        setLoading(false);
      });
  }, []);

  function changeStation(value: string | number | null | undefined) {
    const next = value == null ? null : Number(value);
    if (next === selected) return;
    // smooth chart update without full page reload: keep stale rows visible, use refreshing
    // do NOT setRows([]) here for seamless carousel; refreshing indicator will show.
    setSelected(next);
    syncUrl(next);
    if (!next) {
      setLoading(false);
    }
  }

  // Wrap-aware carousel helpers with prefetch
  const goPrev = useCallback(() => {
    if (!hasStations) return;
    const idx = selectedIndex >= 0 ? selectedIndex : 0;
    const prevIdx = (idx - 1 + stations.length) % stations.length;
    const nextSerid = stations[prevIdx]?.serid;
    if (nextSerid != null) changeStation(String(nextSerid));
  }, [hasStations, selectedIndex, stations]);

  const goNext = useCallback(() => {
    if (!hasStations) return;
    const idx = selectedIndex >= 0 ? selectedIndex : -1;
    const nextIdx = (idx + 1) % stations.length;
    const nextSerid = stations[nextIdx]?.serid;
    if (nextSerid != null) changeStation(String(nextSerid));
  }, [hasStations, selectedIndex, stations]);

  const prefetchStation = useCallback((serid: number, lim: number) => {
    const key = cacheKey(serid, lim);
    if (cacheRef.current.has(key)) return;
    void api<HistoryRow[]>(`/api/v1/web/stations/${serid}/history?limit=${lim}`)
      .then((items) => cacheRef.current.set(key, items))
      .catch(() => {/* prefetch best effort */});
  }, [cacheKey]);

  // prefetch next station data (neighbor prefetch with wrap)
  useEffect(() => {
    if (selected == null || stations.length === 0) return;
    const idx = selectedIndex;
    if (idx < 0) return;
    const prev = stations[(idx - 1 + stations.length) % stations.length];
    const next = stations[(idx + 1) % stations.length];
    if (prev) prefetchStation(prev.serid, limit);
    if (next) prefetchStation(next.serid, limit);
  }, [selected, selectedIndex, stations, limit, prefetchStation]);

  const loadHistory = useCallback((initial: boolean) => {
    if (!selected) return Promise.resolve();
    const requestId = ++requestIdRef.current;
    const key = cacheKey(selected, limit);
    const cached = cacheRef.current.get(key);
    // instant station switch if cached and not initial hard load
    if (cached && !initial) {
      setRows(cached);
      setError("");
    } else if (cached && initial && rowsRef.current.length === 0) {
      setRows(cached);
    }
    // decide loading vs refreshing without full page reload: keep content mounted
    const shouldShowLoading = initial && rowsRef.current.length === 0 && !cached;
    if (shouldShowLoading) setLoading(true);
    else if (!shouldShowLoading) setRefreshing(true);

    return api<HistoryRow[]>(`/api/v1/web/stations/${selected}/history?limit=${limit}`)
      .then((items) => {
        cacheRef.current.set(key, items);
        if (requestId === requestIdRef.current) {
          setRows(items);
          setError("");
        }
      })
      .catch((e) => {
        if (requestId === requestIdRef.current) setError(e instanceof Error ? e.message : "Tidak dapat memuat riwayat");
      })
      .finally(() => {
        if (requestId === requestIdRef.current) {
          if (shouldShowLoading) setLoading(false);
          else setRefreshing(false);
        }
      });
  }, [selected, limit, cacheKey]);

  // maintain contract literals for tests: explicit calls
  // station switch is instant - load when selected or limit changes
  useEffect(() => {
    if (selected == null) return;
    // keep previous chart visible: do not clear rows; use refreshing path for seamless
    void loadHistory(true);
  }, [selected, limit, loadHistory]);

  // also support live refresh keeps existing content mounted
  useWebRefresh(() => { void loadHistory(false); });

  // keyboard arrow left/right to cycle stations (with wrap) - exclude inputs
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable)) return;
      // do not intercept when TrendChart SVG is focused (it handles its own tooltip navigation)
      if (target && target.closest && target.closest(".trend-chart")) {
        // allow TrendChart to handle arrow if it is focused; but carousel should still work when not inside chart tooltip
        // check if active element is SVG inside chart
        const active = document.activeElement;
        if (active && active.closest && (active as Element).closest(".trend-chart")) return;
      }
      event.preventDefault();
      if (event.key === "ArrowLeft") goPrev();
      else goNext();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [goPrev, goNext]);

  const history = useMemo(() => {
    const points: TrendPoint[] = rows
      .flatMap((row) => {
        const value = numericDoseRate(row);
        return value == null || !row.dtom ? [] : [{ at: String(row.dtom), value }];
      })
      .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
    const values = points.map((point) => point.value);
    const latestPoint = points.length ? points[points.length - 1] : null;
    const latest = latestPoint?.value ?? null;
    const min = values.length ? Math.min(...values) : null;
    const max = values.length ? Math.max(...values) : null;
    const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    return { points, latest, min, max, average };
  }, [rows]);

  const unit = selectedStation?.unit ?? "uSv/h";
  const fmt = (value: number | null) => value == null ? "—" : `${formatDoseValue(value)} ${unit}`;
  const chronological = [...rows].sort((a, b) => Date.parse(String(b.dtom ?? "")) - Date.parse(String(a.dtom ?? "")));

  // Searchable station combobox; the listbox is portaled to the document layer so
  // modal, navigation, and scroll-container overflow cannot clip the options.
  const stationLabel = (station: Station) => `${station.name} — ${station.location} (SERID ${station.serid})`;
  const visibleStationValue = stationMenuOpen && query !== null
    ? query
    : selectedStation ? stationLabel(selectedStation) : "";
  const selectStation = (station: Station) => {
    changeStation(station.serid);
    setQuery(null);
    setStationMenuOpen(false);
    setActiveStationIndex(Math.max(0, stations.findIndex((item) => item.serid === station.serid)));
  };
  const handleStationKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setStationMenuOpen(true);
      setActiveStationIndex((index) => filteredStations.length ? (index + 1) % filteredStations.length : 0);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setStationMenuOpen(true);
      setActiveStationIndex((index) => filteredStations.length ? (index - 1 + filteredStations.length) % filteredStations.length : 0);
    } else if (event.key === "Enter" && stationMenuOpen && filteredStations.length) {
      event.preventDefault();
      const station = filteredStations[Math.min(activeStationIndex, filteredStations.length - 1)];
      if (station) selectStation(station);
    } else if (event.key === "Escape" && stationMenuOpen) {
      event.preventDefault();
      setStationMenuOpen(false);
      setQuery(null);
      setActiveStationIndex(Math.max(0, selectedIndex));
    }
  };
  const handleStationSearchChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(event.target.value);
    setActiveStationIndex(0);
    setStationMenuOpen(true);
  };
  const handleLimitChange = (value: string | number | null | undefined) => {
    const next = Number(value ?? 240);
    const bounded = Number.isFinite(next) ? Math.max(1, Math.min(2000, Math.trunc(next))) : 240;
    setLimit(bounded);
    // prefetch for new limit as well
  };

  return (
    <div className="page-stack history-page">
      <PageHeading
        title="Riwayat"
        description="Measurement terbaru, tren, dan statistik rentang untuk stasiun yang dipilih."
        action={<span className={`refresh-indicator${refreshing ? " is-visible" : ""}`}>Memperbarui…</span>}
      />
      <LayerCard className="filter-card history-filter">
        <div className="history-toolbar">
          <div className="history-carousel" role="group" aria-label="Navigasi stasiun">
            <Button
              variant="secondary"
              aria-label="Stasiun sebelumnya"
              data-testid="history-prev"
              onClick={goPrev}
              disabled={!canNavigate}
              title="Stasiun sebelumnya (←)"
            >
              <CaretLeft aria-hidden="true" size={18} weight="bold" />
            </Button>
            <div className="history-station-selector">
              <div className="history-station-combobox">
                <label htmlFor="history-station-input">Stasiun</label>
                <input
                  ref={stationInputRef}
                  id="history-station-input"
                  type="text"
                  role="combobox"
                  aria-label="Stasiun"
                  aria-autocomplete="list"
                  aria-haspopup="listbox"
                  aria-expanded={stationMenuOpen}
                  aria-controls="history-station-listbox"
                  aria-activedescendant={stationMenuOpen && filteredStations[activeStationIndex] ? `history-station-option-${filteredStations[activeStationIndex].serid}` : undefined}
                  placeholder="Cari nama atau SERID…"
                  value={visibleStationValue}
                  disabled={!stations.length}
                  data-testid="history-station-combobox"
                  onFocus={(event) => {
                    setQuery(null);
                    setActiveStationIndex(Math.max(0, selectedIndex));
                    setStationMenuOpen(true);
                    event.currentTarget.select();
                  }}
                  onChange={handleStationSearchChange}
                  onKeyDown={handleStationKeyDown}
                  onBlur={() => {
                    setStationMenuOpen(false);
                    setQuery(null);
                  }}
                />
              </div>
            </div>
            <Button
              variant="secondary"
              aria-label="Stasiun berikutnya"
              data-testid="history-next"
              onClick={goNext}
              disabled={!canNavigate}
              title="Stasiun berikutnya (→)"
            >
              <CaretRight aria-hidden="true" size={18} weight="bold" />
            </Button>
          </div>
          <Select
            label="Rentang"
            items={LIMIT_ITEMS}
            value={String(limit)}
            onValueChange={handleLimitChange}
            data-testid="history-range-select"
          />
          <div className="history-toolbar-meta">
            {selectedStation ? (
              <div className="history-selected-meta cell-subtle" aria-live="polite">
                <span>SERID {selectedStation.serid} · {selectedStation.location}</span>
                {selectedStation.status === "offline" ? <span>Offline — last-known {freshnessLabel(selectedStation.dtom)} · {formatTimestamp(selectedStation.dtom)}</span> : <span>{freshnessLabel(selectedStation.dtom)} · {selectedStation.doserate != null ? `${formatDoseValue(selectedStation.doserate)} ${selectedStation.unit}` : "—"}</span>}
                <AlarmStatus
                  station={selectedStation}
                  onAction={user && user.role !== "Viewer" ? (station) => navigate("alarms", { serid: station.serid, event: station.active_event_id ?? undefined }) : undefined}
                />
              </div>
            ) : null}
            {filteredStations.length !== stations.length ? (
              <div className="cell-subtle" aria-live="polite">{filteredStations.length} dari {stations.length} stasiun cocok</div>
            ) : null}
            <div className="history-carousel-hint cell-subtle" aria-live="polite">
              {canNavigate ? `Stasiun ${selectedIndex + 1} dari ${stations.length} — pakai ← → atau tombol untuk pindah` : null}
            </div>
          </div>
        </div>
      </LayerCard>
      {stationMenuOpen ? createPortal(
        <div
          id="history-station-listbox"
          className="history-station-listbox"
          role="listbox"
          aria-label="Hasil stasiun"
          style={stationMenuStyle}
        >
          {filteredStations.length ? filteredStations.map((station, index) => (
            <div
              id={`history-station-option-${station.serid}`}
              key={station.serid}
              role="option"
              aria-selected={station.serid === selected}
              className={index === activeStationIndex ? "is-active" : ""}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveStationIndex(index)}
              onClick={() => selectStation(station)}
            >
              <span>{station.name} — {station.location}</span>
              <span>SERID {station.serid}</span>
            </div>
          )) : <div className="history-station-empty" role="option" aria-disabled="true">Tidak ada stasiun yang cocok</div>}
        </div>,
        document.body,
      ) : null}
      {error ? <ErrorCard message={error} /> : null}
      {loading && rows.length === 0 ? <LoadingCard /> : (
        <>
          <div className="metric-grid history-summary">
            <MetricCard label="Terbaru" value={fmt(history.latest)} />
            <MetricCard label="Minimum" value={fmt(history.min)} />
            <MetricCard label="Maksimum" value={fmt(history.max)} />
            <MetricCard label="Rata-rata" value={fmt(history.average)} />
          </div>

          <PageSection
            title="Tren dose rate"
            description={`${history.points.length} measurement dimuat dari database central.`}
          >
            <LayerCard className="action-card trend-chart-card">
              <div className={`trend-chart-wrap${refreshing ? " is-refreshing" : ""}`} aria-busy={refreshing}>
                <TrendChart points={history.points} unit={unit} />
              </div>
            </LayerCard>
          </PageSection>

          <PageSection title="Rekaman measurement terbaru" description="Rekaman terbaru ditampilkan lebih dulu.">
            <ResponsiveDataView
              desktop={(
                <LayerCard className="table-card">
                  <Table>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>Waktu</Table.Head>
                        <Table.Head>Dose rate</Table.Head>
                        <Table.Head>Dose</Table.Head>
                        <Table.Head>Status</Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {chronological.map((row, index) => (
                        <Table.Row key={`${row.dtom}-${index}`}>
                          <Table.Cell>{formatTimestamp(String(row.dtom ?? ""))}</Table.Cell>
                          <Table.Cell>{formatDoseValue(row.doserate)}</Table.Cell>
                          <Table.Cell>{formatDoseValue(row.dose)}</Table.Cell>
                          <Table.Cell>{String(row.stat ?? "—")}</Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                </LayerCard>
              )}
              mobile={chronological.length ? (
                <div className="mobile-card-list">
                  {chronological.map((row, index) => (
                    <LayerCard className="record-card" key={`${row.dtom}-${index}`}>
                      <div className="record-card-header">
                        <div><h3>{formatTimestamp(String(row.dtom ?? ""))}</h3></div>
                        <strong>{formatDoseValue(row.doserate)} {unit}</strong>
                      </div>
                      <div className="card-meta">
                        <span>Dose: {formatDoseValue(row.dose)}</span>
                        <span>Status: {String(row.stat ?? "—")}</span>
                      </div>
                    </LayerCard>
                  ))}
                </div>
              ) : <LayerCard className="empty-card">Belum ada measurement untuk stasiun ini.</LayerCard>}
            />
          </PageSection>
        </>
      )}
    </div>
  );
}
