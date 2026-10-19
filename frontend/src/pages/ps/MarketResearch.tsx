import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { GateChip, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { arcApi } from "../../services/arcApi";
import { GenevaChat } from "../../components/geneva/GenevaChat";
import { setActiveClientId, useActiveClientId } from "../../layouts/navConfig";
import ClientOverview from "../client/ClientOverview";
import { IpsHistory } from "../client/IpsHistory";
import { ClientParamProvider } from "../../components/ps/EmbeddedClient";
import { ClientStrip, PS_STEPS } from "./psShared";

export default function MarketResearch() {
  const [params, setParams] = useSearchParams();
  const clientId = useActiveClientId();
  const urlClient = params.get("client");
  useEffect(() => { if (urlClient) setActiveClientId(urlClient); }, [urlClient]);
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  type Tab = "research" | "client360" | "ips";
  const rawTab = params.get("tab");
  const tab: Tab = (["research", "client360", "ips"] as const).find((t) => t === rawTab) ?? "research";
  const setTab = (t: Tab) => setParams((p) => { const n = new URLSearchParams(p); if (t === "research") n.delete("tab"); else n.set("tab", t); return n; }, { replace: true });
  return (
    <div>
      <PageHeader eyebrow="Product Specialist" title="AI Assistant"
        actions={
          <GateChip id="G3" state="not_started" />
        } />
      <Stepper steps={PS_STEPS} current={0} />
      <ClientStrip client={client} />

      <div role="tablist" className="mb-10 flex gap-8 border-b border-hairline">
        {([["research", "AI Assistant"], ["client360", "Client 360"], ["ips", "Client IPS"]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`-mb-px cursor-pointer border-b-2 pb-3 text-base ${tab === k ? "border-brand font-semibold text-ink" : "border-transparent text-ink-muted hover:text-ink"}`}>{label}</button>
        ))}
      </div>

      <div hidden={tab !== "research"}><GenevaChat key={clientId} role="ps" clientId={clientId} /></div>
      {tab === "client360" && <ClientParamProvider clientId={clientId}><ClientOverview /></ClientParamProvider>}
      {tab === "ips" && <Section title="Client IPS"><IpsHistory clientId={clientId} clientName={client?.name} /></Section>}
    </div>
  );
}
