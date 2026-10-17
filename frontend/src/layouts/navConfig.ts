import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import {
  BookUser,
  ClipboardCheck,
  Inbox,
  Layers,
  SlidersHorizontal,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import type { Role } from "../types/arc";

export interface NavItem {
  label: string;
  /** Absolute path. */
  to: string;
  icon: LucideIcon;
  end?: boolean;
}

export const ROLE_PEOPLE: Record<Role, { name: string; person: string; blurb: string; home: string }> = {
  rm: {
    name: "Relationship Manager",
    person: "Isabel",
    blurb: "Owns the client, the IPS and the final pack",
    home: "/rm/clients",
  },
  ic: {
    name: "Investment Counsellor",
    person: "Wei Lun",
    blurb: "Owns the 3L, SAA and TAA",
    home: "/ic/inbox",
  },
  ps: {
    name: "Product Specialist",
    person: "David",
    blurb: "Owns the product list",
    home: "/ps/inbox",
  },
};

/** At most 6 items per role (Lux density limit). */
export function getNav(role: Role, clientId: string): NavItem[] {
  const id = clientId;
  switch (role) {
    case "rm":
      return [
        { label: "Client Book", to: "/rm/clients", icon: BookUser },
        { label: "AI Assistant", to: "/rm/assistant", icon: Sparkles },
      ];
    case "ic":
      return [
        { label: "Requests Inbox", to: "/ic/inbox", icon: Inbox },
        { label: "3L And SAA", to: `/ic/requests/${id}/3l`, icon: Layers },
        { label: "Tactical Review", to: `/ic/cases/${id}/taa`, icon: SlidersHorizontal },
        { label: "Review Pack", to: `/ic/cases/${id}/pack`, icon: ClipboardCheck },
      ];
    case "ps":
      return [
        { label: "Product Requests", to: "/ps/inbox", icon: Inbox },
        { label: "Client Book", to: "/ps/clients", icon: BookUser },
        { label: "AI Assistant", to: "/ps/assistant", icon: Sparkles },
      ];
  }
}

const STORAGE_KEY = "arc.activeClient";
const VALID_IDS = ["ser", "dso", "teo", "jfr", "sha"];
const DEFAULT_ID = "ser";

function isValid(id: string | null | undefined): id is string {
  return !!id && VALID_IDS.includes(id);
}

function readStored(): string | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return isValid(v) ? v : null;
  } catch {
    return null;
  }
}

function writeStored(id: string) {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* storage unavailable */
  }
}

function idFromPath(pathname: string): string | null {
  const m =
    pathname.match(/\/clients\/([^/]+)/) ?? pathname.match(/\/(?:requests|cases)\/([^/]+)/);
  const id = m?.[1];
  // "clients" itself is the list route, never an id.
  if (!id || id === "clients") return null;
  return isValid(id) ? id : null;
}

/** The shell sits above route params, so derive the client from the pathname. */
export function setActiveClientId(id: string) {
  if (VALID_IDS.includes(id)) writeStored(id);
}

export function useActiveClientId(): string {
  const { pathname } = useLocation();
  const fromPath = idFromPath(pathname);

  useEffect(() => {
    if (fromPath) writeStored(fromPath);
  }, [fromPath]);

  return fromPath ?? readStored() ?? DEFAULT_ID;
}
