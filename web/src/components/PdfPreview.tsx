import { useEffect, useState, type SyntheticEvent } from "react";

type PdfPreviewProps = {
  src: string;
  downloadHref?: string;
  title?: string;
};

function responseError(response: Response): Error {
  if (response.status === 401) return new Error("Sesi berakhir. Masuk kembali untuk melihat PDF.");
  if (response.status === 403) return new Error("Anda tidak berhak melihat PDF laporan ini.");
  if (response.status === 404) return new Error("PDF laporan tidak ditemukan.");
  if (response.status === 409) return new Error("PDF belum siap. Tunggu sampai status laporan selesai.");
  if (response.status === 422) return new Error("Pilihan laporan tidak valid. Periksa stasiun dan rentang waktu.");
  return new Error(`PDF tidak dapat dimuat (${response.status} ${response.statusText}).`);
}

async function checkPdf(url: string, signal: AbortSignal): Promise<void> {
  const response = await fetch(url, {
    method: "HEAD",
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/pdf" },
    signal,
  });
  if (!response.ok) throw responseError(response);
  if (!response.headers.get("content-type")?.toLowerCase().includes("application/pdf")) {
    throw new Error("Server tidak mengembalikan file PDF.");
  }
}

/**
 * Render the authenticated same-origin PDF response with the browser's
 * native viewer.  The HEAD probe gives actionable HTTP errors before the
 * browser plugin is asked to render; the iframe then loads the real PDF URL,
 * not a blob URL that would be rejected by the application's strict CSP.
 */
export function PdfPreview({ src, downloadHref = src, title = "Pratinjau PDF laporan" }: PdfPreviewProps) {
  const [state, setState] = useState<"checking" | "ready" | "loaded" | "error">("checking");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setState("checking");
    setError("");
    checkPdf(src, controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setState("ready");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "PDF tidak dapat dimuat.");
          setState("error");
        }
      });
    return () => controller.abort();
  }, [src]);

  function handleFrameLoad(event: SyntheticEvent<HTMLIFrameElement>) {
    // HTTP error responses can still fire iframe onLoad.  Same-origin JSON or
    // HTML is therefore reported instead of leaving an apparently blank PDF
    // pane; the native PDF plugin's document is intentionally inaccessible.
    try {
      const contentType = event.currentTarget.contentDocument?.contentType?.toLowerCase();
      if (contentType && !contentType.includes("pdf") && !contentType.includes("application/octet-stream")) {
        setError("Server tidak mengembalikan PDF. Periksa status laporan lalu coba lagi.");
        setState("error");
        return;
      }
    } catch {
      // Browser PDF viewers commonly expose a protected extension document.
    }
    setState("loaded");
  }

  return <div className="report-pdf-viewer" aria-busy={state === "checking" || state === "ready"}>
    {state === "checking" ? <p role="status">Memuat PDF…</p> : null}
    {state === "error" ? <p className="report-preview-error" role="alert">{error}</p> : null}
    {state === "error" ? <a className="report-download-link" href={downloadHref} download>Unduh PDF</a> : null}
    {state === "ready" || state === "loaded" ? <iframe
      title={title}
      src={src}
      onLoad={handleFrameLoad}
      onError={() => {
        setError("Browser tidak dapat menampilkan PDF. Unduh file untuk membukanya.");
        setState("error");
      }}
    /> : null}
  </div>;
}
