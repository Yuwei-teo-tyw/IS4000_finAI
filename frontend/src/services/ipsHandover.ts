import { arcApi } from "./arcApi";
import { activateIps, mirrorIpsStatus, notifyClientChanged, withdrawIpsFromPm } from "./workflowStore";

/** PM signs off (DB-backed client): backend first, then the browser cache. Throws the backend message when refused. */
export async function returnPmIpsToRm(clientId: string): Promise<void> {
  await arcApi.returnPmIps(clientId);
  mirrorIpsStatus(clientId, "Returned by PM");
}

/** RM "Make IPS active" (DB-backed client): the backend activates and moves the client to Monitoring; the cache and the client view then refresh from it. */
export async function activateIpsAtBackend(clientId: string, version: number): Promise<void> {
  await arcApi.activateIpsVersion(clientId, version);
  mirrorIpsStatus(clientId, "Returned by PM");
  activateIps(clientId, version, { skipBackend: true });
  notifyClientChanged(clientId);
}

/**
 * Brings the browser cache of send/return status in line with the backend for a DB-backed client (after a reload or in a new session).
 * Mock clients are not in the backend book, so the call is refused and the local state is kept as it is.
 */
export async function syncIpsSendFromBackend(clientId: string): Promise<void> {
  let st: Awaited<ReturnType<typeof arcApi.getIpsSendStatus>>;
  try { st = await arcApi.getIpsSendStatus(clientId); } catch { return; }
  withdrawIpsFromPm(clientId);
  if (!st.sent) return;
  mirrorIpsStatus(clientId, "Sent to PM");
  if (st.status === "Returned by PM") mirrorIpsStatus(clientId, "Returned by PM");
}

/**
 * RM "Make active" / G1 approval from any screen (IPS History, IPS Approval).
 * DB-backed client: the backend is asked first, and only the version the PM returned can be activated; a refusal is thrown with its message.
 * Local (mock) client: the browser G1 flow. Phase changes only through these two paths.
 */
export async function activateIpsForClient(clientId: string, version: number): Promise<void> {
  let st: Awaited<ReturnType<typeof arcApi.getIpsSendStatus>> | null = null;
  try { st = await arcApi.getIpsSendStatus(clientId); } catch { st = null; }
  if (st && st.sentVersion != null) {
    if (st.status !== "Returned by PM") throw new Error("The Portfolio Manager has not returned this IPS yet.");
    if (st.sentVersion !== version) throw new Error(`Only the version the Portfolio Manager returned (v${st.sentVersion}) can be made active.`);
    await activateIpsAtBackend(clientId, version);
    return;
  }
  if (!activateIps(clientId, version)) throw new Error("Send the IPS to the Portfolio Manager and get it returned before making it active.");
}
