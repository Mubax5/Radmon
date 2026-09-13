import { useEffect, useState } from "react";
import { api, type Station } from "../api";
import { ErrorCard, LoadingCard, PageHeading, StationTable } from "../ui";

export function StationsPage() {
  const [stations, setStations] = useState<Station[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Station[]>("/api/v1/web/stations").then(setStations).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <PageHeading title="Stations" description="Configured radiation monitoring stations." />
      {error ? <ErrorCard message={error} /> : stations ? <StationTable stations={stations} /> : <LoadingCard />}
    </>
  );
}
