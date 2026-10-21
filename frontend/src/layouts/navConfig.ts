import { useEffect, useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";
import {
  BookUser,
  Inbox,
  Layers,
  Library,
  ScrollText,
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
export function getNav(role: Role, _clientId: string): NavItem[] {
  switch (role) {
    case "rm":
      return [
        { label: "Client Book", to: "/rm/clients", icon: BookUser },
        { label: "AI Assistant", to: "/rm/assistant", icon: Sparkles },
        { label: "House View Records", to: "/rm/house-views", icon: ScrollText },
      ];
    case "ic":
      return [
        { label: "Inbox", to: "/ic/inbox", icon: Inbox },
        { label: "Client Book", to: "/ic/clients", icon: BookUser },
        { label: "AI Assistant", to: "/ic/assistant", icon: Sparkles },
        { label: "House View Records", to: "/ic/house-views", icon: ScrollText },
      ];
    case "ps":
      return [
        { label: "Inbox", to: "/ps/inbox", icon: Inbox },
        { label: "Client Book", to: "/ps/clients", icon: BookUser },
        { label: "AI Assistant", to: "/ps/assistant", icon: Sparkles },
        { label: "House View Records", to: "/ps/house-views", icon: ScrollText },
        { label: "Product Shelf", to: "/ps/shelf", icon: Library },
        { label: "Asset Class Views", to: "/ps/asset-views", icon: Layers },
      ];
  }
}

const STORAGE_KEY = "arc.activeClient";
// Every client in the client book (mock/data.ts `clients`); an id missing here cannot be selected anywhere.
const VALID_IDS = ["ser", "dso", "jfr", "teo", "sha"];
const DEFAULT_ID = "jfr";

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

const listeners = new Set<() => void>();
let current: string = readStored() ?? DEFAULT_ID;
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
const getSnapshot = () => current;

/** Reactive: every subscriber (shell, chat, pages) updates at once. */
export function setActiveClientId(id: string) {
  if (!VALID_IDS.includes(id)) return;
  writeStored(id);
  if (current !== id) { current = id; listeners.forEach((fn) => fn()); }
}

/** Replace the client id segment of a route (/rm/clients/:id, /ic/cases/:id, /ps/cases/:id, /ic/requests/:id) so the same page opens for another client. */
export function pathForClient(pathname: string, id: string): string | null {
  const m = pathname.match(/^(.*\/(?:clients|requests|cases)\/)([^/]+)(.*)$/);
  if (!m || !isValid(m[2])) return null;
  return `${m[1]}${id}${m[3]}`;
}

export function useActiveClientId(): string {
  const { pathname } = useLocation();
  const stored = useSyncExternalStore(subscribe, getSnapshot);
  const fromPath = idFromPath(pathname);

  useEffect(() => {
    if (fromPath && fromPath !== current) { current = fromPath; writeStored(fromPath); listeners.forEach((fn) => fn()); }
  }, [fromPath]);

  return fromPath ?? stored;
}
