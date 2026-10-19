import { PageHeader } from "../../components/ui";
import { GenevaChat } from "../../components/geneva/GenevaChat";
import { useActiveClientId } from "../../layouts/navConfig";

/** Full-page Geneva chat for the Investment Counsellor. The client is switched from the chat's client pill. */
export default function IcAssistant() {
  const clientId = useActiveClientId();
  return (
    <div>
      <PageHeader eyebrow="Investment Counsellor" title="AI Assistant" subtitle="Analyse the portfolio and propose a TAA." />
      <GenevaChat key={clientId} role="ic" clientId={clientId} />
    </div>
  );
}
