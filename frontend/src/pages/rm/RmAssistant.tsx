import { PageHeader } from "../../components/ui";
import { GenevaChat } from "../../components/geneva/GenevaChat";
import { useActiveClientId } from "../../layouts/navConfig";

/** Full-page Geneva chat for the Relationship Manager. The client is switched from the chat's client pill. */
export default function RmAssistant() {
  const clientId = useActiveClientId();
  return (
    <div>
      <PageHeader eyebrow="Relationship Manager" title="AI Assistant" subtitle="Ask about a client's IPS, goals and meetings." />
      <GenevaChat key={clientId} role="rm" clientId={clientId} />
    </div>
  );
}
