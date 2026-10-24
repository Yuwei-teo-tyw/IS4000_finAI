import { PageHeader } from "../../components/ui";
import { GenevaChat } from "../../components/geneva/GenevaChat";
import { useActiveClientId } from "../../layouts/navConfig";

/** Full-page Geneva chat for the Portfolio Manager. The client is switched from the chat's client pill. */
export default function PmAssistant() {
  const clientId = useActiveClientId();
  return (
    <div>
      <PageHeader eyebrow="Portfolio Manager" title="AI Assistant" subtitle="Analyse the portfolio and propose a TAA." />
      <GenevaChat key={clientId} role="pm" clientId={clientId} />
    </div>
  );
}
