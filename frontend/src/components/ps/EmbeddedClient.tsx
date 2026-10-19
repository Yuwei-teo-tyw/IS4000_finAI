import type { ReactNode } from "react";
import { useContext } from "react";
import { UNSAFE_RouteContext } from "react-router-dom";

/** Provides the clientId route param so pages built on useClient() (which reads useParams) can be embedded in tabs. */
export function ClientParamProvider({ clientId, children }: { clientId: string; children: ReactNode }) {
  const parent = useContext(UNSAFE_RouteContext);
  const match = { params: { clientId }, pathname: "", pathnameBase: "", route: { id: "embedded-client", path: ":clientId" } };
  return <UNSAFE_RouteContext.Provider value={{ ...parent, matches: [...parent.matches, match] }}>{children}</UNSAFE_RouteContext.Provider>;
}
