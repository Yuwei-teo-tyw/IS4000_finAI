import { useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { useAsyncResult } from "../ui";

export function useClient() {
  const { clientId = "jfr" } = useParams();
  // Wrapped so "lookup finished, no such client" is distinguishable from "still loading".
  const { data, error } = useAsyncResult(async () => ({ client: await arcApi.getClient(clientId) }), [clientId]);
  const notFound = !!error || (!!data && !data.client);
  return { clientId, client: data?.client, notFound };
}
