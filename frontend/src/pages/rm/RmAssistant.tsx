import { useState } from "react";
import { PageHeader, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import { GenevaChat } from "../../components/geneva/GenevaChat";
import { setActiveClientId, useActiveClientId } from "../../layouts/navConfig";

/** Full-page Geneva chat for the Relationship Manager. */
export default function RmAssistant() {
  const [clientId, setClientId] = useState(useActiveClientId());
  const clients = useAsync(() => arcApi.listClients());
  const change = (id: string) => { setActiveClientId(id); setClientId(id); };
  return (
    <div>
      <PageHeader eyebrow="Relationship Manager" title="AI Assistant" subtitle="Ask about a client's IPS, goals and meetings."
        actions={
          <label className="flex items-center gap-3 text-sm text-ink-muted">
            Client
            <select value={clientId} onChange={(e) => change(e.target.value)} className="rounded-sm border border-hairline-strong bg-surface-100 px-4 py-2.5 text-[15px] text-ink">
              {(clients ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        } />
      <GenevaChat key={clientId} role="rm" clientId={clientId} />
    </div>
  );
}
