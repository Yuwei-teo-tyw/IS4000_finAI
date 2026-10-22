/** The IPS SAA request steps the PM walks through (3L, an SAA per bucket, combined review, send back). */
export const PM_STEPS = [
  { label: "Client profile and 3L", hint: "IPS parts 1 to 3, part 2" },
  { label: "SAA for each bucket", hint: "Liquidity, Longevity, Legacy" },
  { label: "Combined review", hint: "IPS part 4" },
  { label: "Send back to RM", hint: "Return to RM" },
];
