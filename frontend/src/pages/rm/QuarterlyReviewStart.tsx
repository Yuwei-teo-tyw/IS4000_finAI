import { useParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Button, Card, GateChip, Loading, NextAction, PageHeader, Section, useAsync } from "../../components/ui";
import { sendReviewRequest, withdrawReviewRequest, useReviewRequest } from "../../services/workflowStore";

export default function QuarterlyReviewStart() {
  const { clientId = "" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const gates = useAsync(() => arcApi.getGates(clientId), [clientId]);
  const activity = useAsync(() => arcApi.getActivity(clientId), [clientId]);
  const started = !!useReviewRequest(clientId);
  if (!client || !gates || !activity) return <Loading />;
  const events = started
    ? [{ id: "new", at: new Date().toLocaleString("en-SG"), actor: "RM", text: `Ran quarterly review for ${client.name}; Product Specialist notified` }, ...activity]
    : activity;

  return (
    <div>
      <PageHeader eyebrow={client.name} title="Quarterly review" />
      {started ? (
        <NextAction title="Sent to Product Specialist"
          action={<span className="flex flex-wrap gap-3"><Button to={`/rm/clients/${clientId}/review/pack`}>Preview pack review</Button><Button variant="secondary" onClick={() => withdrawReviewRequest(clientId)}>Withdraw request</Button></span>} />
      ) : (
        <NextAction title="Start the review"
          action={<Button onClick={() => sendReviewRequest(clientId)}>Run quarterly review and send to Product Specialist</Button>} />
      )}

      <Section title="How it flows">
        <Card>
          <div className="flex flex-wrap items-center gap-4 text-sm font-semibold text-ink">
            <span>Product Specialist</span><ArrowRight size={16} />
            <span>Portfolio Manager</span><ArrowRight size={16} />
            <span>You</span>
            <span className="ml-auto flex flex-wrap gap-2">
              {gates.map((g) => <GateChip key={g.id} id={g.id} state={started && g.id !== "G1" ? (g.id === "G4" ? "not_started" : "pending") : g.state} />)}
            </span>
          </div>
        </Card>
      </Section>

      <Section title="Case timeline">
        <Card>
          <ol className="flex flex-col gap-6">
            {events.map((e) => (
              <li key={e.id} className="border-l-2 border-hairline-strong pl-5">
                <p className="text-xs text-ink-500">{e.at} · {e.actor}</p>
                <p className="mt-1 text-sm text-ink-700">{e.text}</p>
              </li>
            ))}
          </ol>
        </Card>
      </Section>
    </div>
  );
}
