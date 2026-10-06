export type DoseValue = number | string | null | undefined;

/** Display policy-event values exactly as supplied by the API; never apply unit scaling here. */
export function formatPolicyMeasurement(event: { measured_value?: DoseValue }): string {
  return formatDoseValue(event.measured_value);
}

/** Format a dose value rounded to exactly two fractional digits. */
export function formatDoseValue(value: DoseValue): string {
  if (value == null) return "—";
  const raw = String(value).trim();
  if (!raw) return "—";
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) return raw;

  const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(String(numeric));
  if (!match) return numeric.toFixed(2);
  const [, sign, integer = "", fraction = "", exponentText = "0"] = match;
  const digits = `${integer || "0"}${fraction}`;
  const decimalPlaces = fraction.length - Number(exponentText);
  const shift = 2 - decimalPlaces;
  let scaled: bigint;
  if (shift >= 0) {
    scaled = BigInt(digits) * 10n ** BigInt(shift);
  } else {
    const cut = digits.length + shift;
    scaled = BigInt(cut > 0 ? digits.slice(0, cut) : "0");
    if (cut >= 0 && digits[cut] >= "5") scaled += 1n;
  }
  const whole = scaled / 100n;
  const cents = String(scaled % 100n).padStart(2, "0");
  return `${sign === "-" && scaled !== 0n ? "-" : ""}${whole}.${cents}`;
}
