export interface ClientProfile {
  dateOfBirth: string; age: number; nationality: string; residency: string; occupation: string; maritalStatus: string;
  dependants: string; incomeSource: string; annualIncome?: string; taxResidency: string; goals: string[];
  timeHorizon: string; liquidityNeeds: string; lossTolerance: string[];
  /** IPS targets, e.g. an SGD amount by a horizon. */
  targets?: { amount?: string | number; currency?: string; horizonYears?: number; text: string; source_note?: string }[];
}

export const profileByClient: Record<string, ClientProfile> = {
  jfr: {
    dateOfBirth: "14 March 1971", age: 55, nationality: "Singaporean", residency: "Singapore", occupation: "Chief Executive Officer", maritalStatus: "Married",
    dependants: "2 children", incomeSource: "Salary and bonus", annualIncome: "About S$10m a year", taxResidency: "Singapore",
    goals: ["Keep capital safe with steady income", "Modest growth through a small blue-chip equity allocation", "Maintain a S$30m cash reserve for living costs"],
    timeHorizon: "Long term (at least ten years)", liquidityNeeds: "About S$150,000 a month in living costs; S$30m cash reserve",
    lossTolerance: ["Very risk averse; a fall above 10% in a year would be very uncomfortable", "Likely to sell after a large drawdown"],
    targets: [{ amount: "800m", currency: "SGD", horizonYears: 5, text: "SGD 800m investment portfolio in 5 years" }],
  },
  dso: {
    dateOfBirth: "2 July 1962", age: 64, nationality: "Singaporean", residency: "Singapore", occupation: "Senior executive, approaching retirement", maritalStatus: "Married",
    dependants: "None; 3 grandchildren", incomeSource: "Salary; pension drawdown planned", taxResidency: "Singapore",
    goals: ["Preserve capital", "Draw steady income in retirement", "Leave a small bequest to grandchildren"],
    timeHorizon: "Short to medium term (retirement may be brought forward by two years)", liquidityNeeds: "Moderate, steady income draw expected from retirement; onboarding in progress",
    lossTolerance: ["Uncomfortable with a fall above 10% in a year", "Likely to sell after a large drawdown", "Risk questionnaire completed; to be confirmed with the Relationship Manager"],
  },
  jdi: {
    dateOfBirth: "30 May 1985", age: 41, nationality: "Singaporean", residency: "Singapore", occupation: "Technology professional", maritalStatus: "Married",
    dependants: "1 child", incomeSource: "Salary; equity compensation", taxResidency: "Singapore",
    goals: ["Build long-term wealth", "Save for the child's education", "Diversify away from employer equity"],
    timeHorizon: "Long term (15+ years)", liquidityNeeds: "Low; onboarding in progress",
    lossTolerance: ["Risk questionnaire pending", "Tolerance to be confirmed with the Relationship Manager"],
  },
};

export const defaultProfile: ClientProfile = profileByClient.jfr;

/** Industry-standard review process, used when the IPS carries no reviewRules. */
export const DEFAULT_REVIEW_RULES: { title: string; text: string }[] = [
  { title: "Periodic review", text: "The Relationship Manager and Portfolio Manager review the portfolio at least quarterly" },
  { title: "Rebalancing", text: "Rebalance when an asset class drifts outside its allowed range around the SAA" },
  { title: "Life events", text: "Review the IPS on any major life event of the client" },
  { title: "Risk profile change", text: "Reissue the IPS on any change in the client risk profile" },
  { title: "Annual IPS review", text: "Confirm objectives, constraints and risk tolerance with the client at least once a year" },
  { title: "Ownership", text: "Portfolio Manager owns the SAA and TAA; Product Specialist owns product selection; Relationship Manager owns the IPS and client contact" },
];
