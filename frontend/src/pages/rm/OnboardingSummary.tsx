import { useState } from "react";
import { useParams } from "react-router-dom";
import { Bot, Check } from "lucide-react";
import { arcApi } from "../../services/arcApi";
import { Badge, Button, Card, GateChip, Loading, PageHeader, Section, Stepper, useAsync } from "../../components/ui";
import { onboardingSteps } from "./rmShared";

const questions = [
  "What is the client's annual income? It was not mentioned in the notes.",
  "Are there existing liabilities, such as a mortgage? I will not assume any.",
];

export default function OnboardingSummary() {
  const { clientId = "" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  const notes = useAsync(() => arcApi.getMeetingNotes(clientId), [clientId]);
  const [kind, setKind] = useState<"Onboarding" | "Ongoing">("Onboarding");
  const [answers, setAnswers] = useState<string[]>(questions.map(() => ""));
  const [todo, setTodo] = useState<Record<number, boolean>>({});
  if (!client || !notes) return <Loading />;
  const note = notes[0];
  const items = note?.checklist ?? [];

  return (
    <div>
      <PageHeader eyebrow={client.name} title="Review the summary" subtitle="Here is what the agent understood from your notes. Correct anything that looks wrong."
        actions={<GateChip id="G1" state="not_started" />} />
      <Stepper steps={onboardingSteps} current={1} />

      <Section title="What I understood" hint="Goals, risks, concerns, amounts and key dates.">
        <Card>
          <div className="flex gap-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-inverse text-ink-inverse"><Bot size={20} /></span>
            <div>
              <ul className="list-disc space-y-3 pl-5 text-base text-ink-700">
                {(note?.summary ?? ["Goals, risks and amounts will appear here."]).map((s, i) => <li key={i}>{s}</li>)}
              </ul>
              <div className="mt-6 flex items-center gap-3 text-sm text-ink-500">
                Detected case type:
                {(["Onboarding", "Ongoing"] as const).map((k) => (
                  <button key={k} onClick={() => setKind(k)} className="cursor-pointer">
                    <Badge tone={kind === k ? "navy" : "grey"}>{k}{kind === k ? " (confirmed)" : ""}</Badge>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </Card>
      </Section>

      <Section title="Questions for you" hint="I never guess missing facts. Please answer these.">
        <div className="flex flex-col gap-5">
          {questions.map((q, i) => (
            <Card key={i}>
              <p className="mb-3 text-sm font-semibold text-ink">{q}</p>
              <input value={answers[i]} onChange={(e) => setAnswers(answers.map((a, j) => (j === i ? e.target.value : a)))}
                placeholder="Your answer" className="w-full rounded-md border border-ink-200 px-4 py-3 text-sm outline-none focus:border-ink" />
            </Card>
          ))}
        </div>
      </Section>

      <Section title="To-do" hint="Follow-ups from the meeting.">
        <Card>
          <ul className="flex flex-col gap-4">
            {items.map((c, i) => {
              const done = todo[i] ?? c.done;
              return (
                <li key={i}>
                  <button onClick={() => setTodo({ ...todo, [i]: !done })} className="flex cursor-pointer items-center gap-3 text-sm">
                    <span className={`flex h-6 w-6 items-center justify-center rounded border ${done ? "border-ink bg-surface-inverse text-ink-inverse" : "border-ink-200"}`}>{done && <Check size={14} />}</span>
                    <span className={done ? "text-ink-500 line-through" : ""}>{c.text}</span>
                  </button>
                </li>
              );
            })}
            {items.length === 0 && <li className="text-sm text-ink-500">No follow-ups yet.</li>}
          </ul>
        </Card>
      </Section>

      <div className="flex justify-end"><Button to={`/rm/clients/${clientId}/ips-draft`}>Continue to IPS draft</Button></div>
    </div>
  );
}
