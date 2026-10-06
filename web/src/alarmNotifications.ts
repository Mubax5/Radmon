export type PolicyAlarmEvent = {
  event_id: string;
  serid: number;
  kind: string;
  status: string;
  reason?: string | null;
  measured_value?: number | null;
  fresh?: boolean;
  offline?: boolean;
};

export function isThresholdAlarm(event: PolicyAlarmEvent): boolean {
  return event.kind === "ALARM" && ["LOW_THRESHOLD", "HIGH_THRESHOLD"].includes(event.reason ?? "");
}

export function freshUndeliveredEvents(
  events: PolicyAlarmEvent[],
  delivered: Set<string>,
): PolicyAlarmEvent[] {
  const fresh = events.filter((event) => isThresholdAlarm(event) && event.fresh !== false && event.offline !== true && !delivered.has(event.event_id));
  fresh.forEach((event) => delivered.add(event.event_id));
  return fresh;
}

export function alarmSoundEnabled(): boolean {
  return localStorage.getItem("radmon-alarm-sound") === "enabled";
}

export function playAlarmSignal(): void {
  if (!alarmSoundEnabled()) return;
  const AudioContextClass = window.AudioContext;
  if (!AudioContextClass) return;
  const context = new AudioContextClass();
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = 880;
  gain.gain.setValueAtTime(0.0001, context.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.18, context.currentTime + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.45);
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start();
  oscillator.stop(context.currentTime + 0.46);
  oscillator.onended = () => { void context.close(); };
}
