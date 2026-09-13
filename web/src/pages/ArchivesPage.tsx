import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorCard, JsonTable, LoadingCard, PageHeading } from "../ui";

export function ArchivesPage() {
  const [items, setItems] = useState<Array<Record<string, unknown>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Array<Record<string, unknown>>>("/api/v1/control/archives")
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <PageHeading title="Archives" description="Verified quarterly archive bundles and retention state." />
      {error ? <ErrorCard message={error} /> : items ? <JsonTable rows={items} empty="No archive bundles yet." /> : <LoadingCard />}
    </>
  );
}
