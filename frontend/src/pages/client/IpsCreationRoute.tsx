import { useClient } from "../../components/client/useClient";
import IpsCreation from "../rm/IpsCreation";

/** Route element for Client 360 "IPS creation" (RM). */
export default function IpsCreationRoute() {
  const { clientId } = useClient();
  return <IpsCreation clientId={clientId} />;
}
