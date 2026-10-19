import PackReview from "./PackReview";

/** Client 360 tab for the RM: the Review Pack view, but over the IPS sections (RM fills, IC proposes the SAA, RM completes). */
export default function IpsCreation({ clientId }: { clientId: string }) {
  return <PackReview embedded clientId={clientId} workflow="ips" />;
}
