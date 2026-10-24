import type { Client } from "../../types/arc";

export { loadSelection, saveSelection } from "../../services/workflowStore";

export const PS_STEPS = [{ label: "Product & Market Research" }, { label: "Send To PM" }];

export function ClientStrip({ client }: { client?: Client }) {
  if (!client) return null;
  return (
    <div className="mb-12 flex flex-wrap items-center gap-x-10 gap-y-3 rounded-lg border border-ink-200 bg-surface-100 px-7 py-4 text-sm">
      <span className="font-semibold text-ink">{client.name}</span>
      <span className="text-ink-700">Risk limit: {client.riskCap} of 5 ({client.riskCategory})</span>
      <span className="text-ink-700">IPS {client.ipsVersion ? `v${client.ipsVersion}` : "not yet issued"}</span>
    </div>
  );
}
