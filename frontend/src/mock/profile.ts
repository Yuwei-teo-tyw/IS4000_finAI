export interface ClientProfile {
  dateOfBirth: string; age: number; nationality: string; residency: string; occupation: string; maritalStatus: string;
  dependants: string; incomeSource: string; taxResidency: string; goals: string[];
  timeHorizon: string; liquidityNeeds: string; lossTolerance: string[];
}

export const profileByClient: Record<string, ClientProfile> = {
  ser: {
    dateOfBirth: "14 March 1971", age: 55, nationality: "Singaporean", residency: "Singapore", occupation: "Chief Executive Officer", maritalStatus: "Married",
    dependants: "2 children", incomeSource: "Salary and bonus; dividend income", taxResidency: "Singapore",
    goals: ["Fund the S$3.0m deposit for a family home within 12 months", "Retain lifetime income", "Leave a legacy for two children"],
    timeHorizon: "Medium to long term (12 months for liquidity, 15+ years for growth)", liquidityNeeds: "High over the next 12 months for the house deposit",
    lossTolerance: ["Can tolerate a drawdown of about 12%", "Volatility concerns have increased since last year"],
  },
  dso: {
    dateOfBirth: "2 July 1962", age: 64, nationality: "Singaporean", residency: "Singapore", occupation: "Senior executive, approaching retirement", maritalStatus: "Married",
    dependants: "None; 3 grandchildren", incomeSource: "Salary; pension drawdown planned", taxResidency: "Singapore",
    goals: ["Preserve capital", "Draw steady income in retirement", "Leave a small bequest to grandchildren"],
    timeHorizon: "Short to medium term (retirement may be brought forward by two years)", liquidityNeeds: "Moderate, steady income draw expected from retirement",
    lossTolerance: ["Uncomfortable with a fall above 10% in a year", "Likely to sell after a large drawdown"],
  },
  teo: {
    dateOfBirth: "21 September 1975", age: 51, nationality: "Singaporean", residency: "Singapore", occupation: "Company director", maritalStatus: "Married",
    dependants: "1 child", incomeSource: "Director fees; investment income", taxResidency: "Singapore",
    goals: ["Grow wealth steadily over the long term", "Fund overseas education for the child", "Maintain a balanced portfolio"],
    timeHorizon: "Long term (10+ years)", liquidityNeeds: "Low to moderate; annual education costs",
    lossTolerance: ["Can tolerate a drawdown of about 15%", "Prefers gradual rebalancing over forced selling"],
  },
  jfr: {
    dateOfBirth: "9 November 1979", age: 46, nationality: "Singaporean", residency: "Singapore", occupation: "Entrepreneur (recent business sale)", maritalStatus: "Single",
    dependants: "None", incomeSource: "Proceeds of business sale; investment income", taxResidency: "Singapore",
    goals: ["Grow wealth over the long term", "Pass assets to family", "Set up a family foundation within five years"],
    timeHorizon: "Long term (10+ years)", liquidityNeeds: "Low; monthly cash needs to be confirmed",
    lossTolerance: ["Can tolerate a drawdown of about 30%", "Comfortable with large swings for long-term growth"],
  },
  sha: {
    dateOfBirth: "30 May 1985", age: 41, nationality: "Singaporean", residency: "Singapore", occupation: "Technology professional", maritalStatus: "Married",
    dependants: "1 child", incomeSource: "Salary; equity compensation", taxResidency: "Singapore",
    goals: ["Build long-term wealth", "Save for the child's education", "Diversify away from employer equity"],
    timeHorizon: "Long term (15+ years)", liquidityNeeds: "Low; onboarding in progress",
    lossTolerance: ["Risk questionnaire pending", "Tolerance to be confirmed with the Relationship Manager"],
  },
};

export const defaultProfile: ClientProfile = profileByClient.ser;
