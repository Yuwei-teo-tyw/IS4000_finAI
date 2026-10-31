import { useState, type InputHTMLAttributes } from "react";

/** Strip leading zeros but keep "0", "0.5", "" and negatives valid: "012" -> "12", "-007" -> "-7". */
export const stripLeadingZeros = (s: string) => s.replace(/^(-?)0+(?=\d)/, "$1");

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value"> & { value: number | string | null | undefined };

/**
 * Shared numeric box. Drop-in for <input type="number">: same props, same onChange (e.target.value is already normalised).
 * Typing a digit after 0 shows "12", never "012", even when the parent state is a number.
 */
export function NumberInput({ value, onChange, onBlur, ...rest }: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft !== null && (draft === "" || draft === "-" || Number(draft) === Number(value)) ? draft : (value ?? "");
  return (
    <input
      {...rest}
      type="number"
      value={shown}
      onChange={(e) => {
        const clean = stripLeadingZeros(e.target.value);
        if (clean !== e.target.value) e.target.value = clean;
        setDraft(clean);
        onChange?.(e);
      }}
      onBlur={(e) => { setDraft(null); onBlur?.(e); }}
    />
  );
}
