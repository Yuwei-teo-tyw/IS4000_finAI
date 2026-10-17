import { useState, type ReactNode } from "react";
import { Download, Eye, X } from "lucide-react";
import { Button } from "../ui";
import { ROLE_LABEL } from "../../types/arc";
import { CompiledDocument, pendingRoles, type DocSection } from "./CompiledDocument";

const PRINT_CSS = `@media print {
  body * { visibility: hidden; }
  .print-area, .print-area * { visibility: visible; }
  .print-area { position: absolute; left: 0; top: 0; width: 100%; max-width: 100%; overflow: visible; }
  .print-area * { overflow: visible !important; height: auto !important; max-height: none !important; }
  .print-area .whitespace-pre-wrap { white-space: pre-wrap; overflow-wrap: anywhere; }
}`;

interface Props {
  docTitle: string; clientName: string; version: string; date: string; sections: DocSection[];
  /** Final export can be blocked (e.g. gate G4 not yet approved). */
  exportBlocked?: boolean; blockedReason?: string;
  /** Replaces the default compiled layout, e.g. the IPS bank-document view. */
  document?: ReactNode;
}

/** "Preview Compiled Document" button + full-screen preview overlay with Export PDF. */
export function ExportActions({ docTitle, clientName, version, date, sections, exportBlocked = false, blockedReason, document }: Props) {
  const [open, setOpen] = useState(false);
  const roles = pendingRoles(sections);
  const complete = roles.length === 0;
  const finalOk = complete && !exportBlocked;
  return (
    <>
      <Button variant="ghost" onClick={() => setOpen(true)}><Eye size={16} />Preview Compiled Document</Button>
      {open && (
        <div className="fixed inset-0 z-50 flex flex-col bg-surface-300 print:static print:block">
          <style>{PRINT_CSS}</style>
          <div className="no-print flex flex-wrap items-center justify-between gap-4 border-b border-hairline bg-surface-100 px-8 py-4">
            <div>
              <h2 className="text-xl">Compiled Document Preview</h2>
              <p className="text-sm text-ink-muted">
                {complete ? "All sections are complete." : `Still owed by: ${roles.map((r) => ROLE_LABEL[r]).join(", ")}.`}
                {exportBlocked && blockedReason ? ` ${blockedReason}` : ""}
              </p>
            </div>
            <div className="flex gap-3">
              <Button variant={finalOk ? "gold" : "ghost"} onClick={() => window.print()}>
                <Download size={16} />{finalOk ? "Export PDF" : "Export Draft PDF"}
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)}><X size={16} />Close</Button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4 sm:px-8 py-10 print:overflow-visible print:p-0">
            <div className="print-area mx-auto w-full min-w-0 max-w-full">
              {document ?? <CompiledDocument docTitle={docTitle} clientName={clientName} version={version} date={date}
                sections={sections} />}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
