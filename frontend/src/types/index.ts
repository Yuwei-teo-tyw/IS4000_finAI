export interface Message {
  role: "user" | "assistant";
  content: string;
  agent_name?: string;
  search_used?: boolean;
}

export interface FinanceResponse {
  message_result: string;
  data: {
    query_type?: string;
    confidence?: number;
    response_length?: number;
    disclaimer?: string;
    search_used?: boolean;
  };
}

export interface MarketResearchResponse {
  message_result: string;
  data: {
    query_type?: string;
    run_id?: string;
    phase?: string | null;
    confidence?: "low" | "medium" | "high";
    recession_prob_12m?: number | null;
    events?: string[];
    failed_sources?: string[];
    disclaimer?: string;
    error?: string;
  };
}

// Reader view of a news article the Market Researcher cited
// (GET /agents/market-researcher/articles).
export interface ArticleView {
  url: string;
  source: string | null;
  title: string | null;
  published: string | null;
  author: string | null;
  summary: string | null;
  topics: string[];
  sentiment: "risk_on" | "risk_off" | "neutral" | null;
  market_impact: "low" | "medium" | "high" | null;
  status: "ok" | "unavailable";
  reason: string | null;
  paragraphs: string[];
}

// A source link the user clicked, identified by the run that cited it.
export interface ArticleRef {
  runId: string;
  url: string;
  title: string;
}

export interface PendingAction {
  action_type?: string;
  amount?: number;
  description?: string;
}

export interface SystemResponse {
  finance_response: FinanceResponse;
  market_research_response?: MarketResearchResponse;
  message: string;
  agent_name?: string;
  info_message?: string;
  requires_confirmation?: boolean;
  pending_action?: PendingAction | null;
}

export interface Session {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}
