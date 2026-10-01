export type DoseValue = number | string | null | undefined;

/** Format a dose value without rounding away measured precision. */
export function formatDoseValue(value: DoseValue): string {
  if (value == null) return "—";
  const raw = String(value).trim();
  if (!raw) return "—";
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) return raw;
  if (numeric === 0) return "0";

  // Keep ordinary decimal strings exact, only removing insignificant zeroes.
  // Exponential inputs use Number's shortest round-trippable representation.
  if (!/[eE]/.test(raw) && /^[-+]?\d*\.\d+$/.test(raw)) {
    return raw.replace(/0+$/, "").replace(/\.$/, "");
  }
  return String(numeric);
}
