import { profileByClient, defaultProfile, type ClientProfile } from "../mock/profile";

export type { ClientProfile };

const delay = <T,>(v: T, ms = 120) => new Promise<T>((r) => setTimeout(() => r(v), ms));

export const profileApi = {
  getClientProfile: (clientId: string): Promise<ClientProfile> => delay(profileByClient[clientId] ?? defaultProfile),
};
