export interface ClientProfile {
  dateOfBirth: string; age: number; nationality: string; residency: string; occupation: string; maritalStatus: string;
  dependants: string; incomeSource: string; taxResidency: string; goals: string[];
  timeHorizon: string; liquidityNeeds: string; lossTolerance: string[];
}

export const profileByClient: Record<string, ClientProfile> = {
  jfr: {
    dateOfBirth: "14 March 1971", age: 55, nationality: "Singaporean", residency: "Singapore", occupation: "Chief Executive Officer", maritalStatus: "Married",
    dependants: "2 children", incomeSource: "Salary and bonus (about S$10m a year)", taxResidency: "Singapore",
    goals: ["Keep capital safe with steady income", "Modest growth through a small blue-chip equity allocation", "Maintain a S$30m cash reserve for living costs"],
    timeHorizon: "Long term (at least ten years)", liquidityNeeds: "About S$150,000 a month in living costs; S$30m cash reserve",
    lossTolerance: ["Very risk averse; a fall above 10% in a year would be very uncomfortable", "Likely to sell after a large drawdown"],
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
