import { useState } from "react";
import { ROLE_PEOPLE } from "../../layouts/navConfig";
import type { Role } from "../../types/arc";

const TAGLINES = [
  "Great relationships are built one thoughtful conversation at a time.",
  "Trust is the quiet foundation of every portfolio.",
  "Today, someone's long-term plan is in good hands.",
  "Listen first. The numbers will follow.",
  "Wealth is a means; your clients' stories are the purpose.",
  "Small moments of care compound like capital.",
  "Clarity for them, calm for you.",
  "Every goal begins with a conversation.",
  "Steady guidance through every market season.",
  "Behind each portfolio is a family's future.",
  "Patience, preparation, and a good question.",
  "Make today's meeting count.",
  "Advice earns trust; trust earns a lifetime of partnership.",
  "The best plans are the ones clients understand and believe in.",
];

/** Landing-page banner shared by every role: photo, "Welcome back, <name>" and a quote. */
export function WelcomeBanner({ role }: { role: Role }) {
  const [tagline] = useState(() => TAGLINES[Math.floor(Math.random() * TAGLINES.length)]);
  return (
    <section
      className="mb-14 flex min-h-44 items-center rounded-lg bg-cover bg-center p-6 md:px-10"
      style={{ backgroundImage: "url(/hero-banner.png), linear-gradient(135deg, #d9d6cc 0%, #b9b6ab 100%)" }}
    >
      <div className="max-w-md rounded-sm bg-[rgb(255_255_255/0.92)] p-5 text-[#1c1c1c] shadow-card">
        <div className="border-l-[3px] border-brand pl-5">
          <h1 className="text-2xl font-light leading-tight">Welcome back, {ROLE_PEOPLE[role].person}</h1>
          <p className="mt-2 text-sm font-light text-[#3a3a3a]">{tagline}</p>
        </div>
      </div>
    </section>
  );
}
