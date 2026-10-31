import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { syncIpsSendFromBackend } from "../../services/ipsHandover";
import type { Client } from "../../types/arc";

type Loaded = { id: string; client?: Client; error?: Error };

/**
 * The client for the :clientId route. Re-reads when the phase may have changed (`client-changed`, sent on IPS activation),
 * keeping the current client on screen meanwhile, so the phase badge and the Review Pack tab update without a remount.
 */
export function useClient() {
  const { clientId = "jfr" } = useParams();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => {
      arcApi.getClient(clientId).then(
        (client) => live && setLoaded({ id: clientId, client }),
        (error) => live && setLoaded({ id: clientId, error: error instanceof Error ? error : new Error(String(error)) }),
      );
    };
    load();
    // The backend is the source of truth for the IPS send/return status; the browser cache follows it on open.
    void syncIpsSendFromBackend(clientId);
    const onChanged = (e: Event) => { if ((e as CustomEvent<{ clientId?: string }>).detail?.clientId === clientId) load(); };
    window.addEventListener("client-changed", onChanged);
    return () => { live = false; window.removeEventListener("client-changed", onChanged); };
  }, [clientId]);
  // Ignore a result left over from the previous client id.
  const current = loaded?.id === clientId ? loaded : undefined;
  // Wrapped so "lookup finished, no such client" is distinguishable from "still loading".
  const notFound = !!current?.error || (!!current && !current.client);
  return { clientId, client: current?.client, notFound };
}
