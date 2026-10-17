import { useParams } from "react-router-dom";
import { arcApi } from "../../services/arcApi";
import { useAsync } from "../ui";

export function useClient() {
  const { clientId = "ser" } = useParams();
  const client = useAsync(() => arcApi.getClient(clientId), [clientId]);
  return { clientId, client };
}
