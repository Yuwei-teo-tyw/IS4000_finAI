import { useEffect, useState } from "react";
import { arcApi, type SearchStatus } from "../../services/arcApi";

/** Search health, polled on mount and every 60s. A failed request counts as unknown (null). */
export function useSearchStatus(): SearchStatus | null {
  const [status, setStatus] = useState<SearchStatus | null>(null);
  useEffect(() => {
    let on = true;
    const load = () => { arcApi.getSearchStatus().then((s) => { if (on) setStatus(s); }).catch(() => { if (on) setStatus(null); }); };
    load();
    const t = window.setInterval(load, 60_000);
    return () => { on = false; window.clearInterval(t); };
  }, []);
  return status;
}
