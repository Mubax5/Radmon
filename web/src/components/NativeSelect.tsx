import type { ChangeEvent, ReactNode } from "react";

type NativeSelectProps = {
  id: string;
  label: string;
  value: string;
  onChange: (event: ChangeEvent<HTMLSelectElement>) => void;
  children: ReactNode;
  disabled?: boolean;
  required?: boolean;
  name?: string;
  testId: string;
};

export function NativeSelect({
  id,
  label,
  value,
  onChange,
  children,
  disabled = false,
  required = false,
  name,
  testId,
}: NativeSelectProps) {
  return (
    <label className="native-select-field" htmlFor={id}>
      <span>{label}</span>
      <select
        id={id}
        name={name}
        className="native-select"
        data-testid={testId}
        aria-label={label}
        value={value}
        onChange={onChange}
        disabled={disabled}
        required={required}
      >
        {children}
      </select>
    </label>
  );
}
