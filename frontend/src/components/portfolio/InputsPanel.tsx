import type { PmInputs } from "../../types/portfolio";
import { Badge, Card } from "../ui";

/** What the Portfolio Manager will receive, with where each value came from. Read-only. */
export function InputsPanel({ inputs }: { inputs: PmInputs }) {
  const captured = inputs.fields.filter((f) => f.value !== null);
  const missing = inputs.fields.filter((f) => f.value === null);
  return (
    <Card>
      <div className="grid gap-x-12 gap-y-5 md:grid-cols-2">
        {captured.map((f) => (
          <div key={f.label} className="border-b border-hairline pb-4">
            <p className="text-xs text-ink-muted">{f.label}</p>
            <p className="mt-1 text-base text-ink">{f.value}</p>
            <p className="mt-1 text-xs text-ink-muted">Source: {f.source}</p>
          </div>
        ))}
      </div>
      {missing.length > 0 && (
        <div className="mt-8">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">Not captured yet</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {missing.map((f) => <Badge key={f.label} tone="amber">{f.label}</Badge>)}
          </div>
          <p className="mt-3 text-sm text-ink-muted">These are sent as missing. The agent reports them rather than guessing.</p>
        </div>
      )}
      {inputs.notes.length > 0 && (
        <ul className="mt-8 list-disc space-y-1 pl-5 text-sm text-ink-muted">
          {inputs.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
    </Card>
  );
}
