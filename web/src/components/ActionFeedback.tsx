export type FeedbackState = { kind: "ok" | "error"; text: string };

export function ActionFeedback({ state }: { state: FeedbackState | null }) {
  if (!state) return null;
  return (
    <div
      className={state.kind === "ok" ? "form-success" : "form-error"}
      role={state.kind === "ok" ? "status" : "alert"}
      aria-live={state.kind === "ok" ? "polite" : "assertive"}
    >
      {state.text}
    </div>
  );
}
