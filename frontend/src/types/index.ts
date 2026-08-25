export interface Message {
  role: "user" | "assistant";
  content: string;
  agent_name?: string;
  search_used?: boolean;
}

export interface TechnicalResponse {
  message_result: string;
  data: {
    query_type?: string;
    confidence?: number;
    response_length?: number;
    search_used?: boolean;
  };
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

export interface PendingAction {
  action_type?: string;
  amount?: number;
  description?: string;
}

export interface SystemResponse {
  technical_response: TechnicalResponse;
  finance_response: FinanceResponse;
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
