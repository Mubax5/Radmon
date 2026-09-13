import { useEffect, useState } from "react";
import { api, type Station } from "../api";
import { useWebRefresh } from "../live";
import { ErrorCard, LoadingCard, PageHeading, StationTable } from "../ui";

export function StationsPage() {
  const [stations, setStations] = useState<Station[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api<Station[]>("/api/v1/web/stations")
    .then((items) => { setStations(items); setError(""); })
    .catch((e) => setError(e.message));

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); });

  return (
    <>
      <PageHeading title="Stations" description="Configured radiation monitoring stations." />
      {error ? <ErrorCard message={error} /> : stations ? <StationTable stations={stations} /> : <LoadingCard />}
    </>
  );
}
