// Thin typed client over the gateway's FastAPI endpoints (gateway/gateway_app.py).
// No runtime dependency beyond the built-in fetch (Node 22+); every response shape here
// mirrors the Pydantic models the server actually returns.

export type RegistryInfo = {
  domain_count: number;
  tool_count: number;
  groups: Record<string, { domains: string[]; can_write: boolean }>;
};

export type ApprovalEntrySummary = {
  approval_id: string;
  tool: string;
  domain: string;
  caller_group: string;
  params: Record<string, unknown>;
  oracle_ok: boolean;
  oracle_reason: string | null;
};

export type CallResult =
  | { status: "ok"; tool: string; data: unknown }
  | {
      status: "pending_approval";
      tool: string;
      approval_id: string;
      oracle_ok: boolean;
      oracle_reason: string | null;
    };

export class GatewayClient {
  constructor(private readonly baseUrl: string) {}

  async getRegistry(): Promise<RegistryInfo> {
    return this.getJson<RegistryInfo>("/registry");
  }

  async issueToken(group: string): Promise<string> {
    const body = await this.postJson<{ token: string }>("/auth/token", { group });
    return body.token;
  }

  async callTool(tool: string, token: string, params: Record<string, unknown>): Promise<CallResult> {
    return this.postJson<CallResult>(`/tools/${encodeURIComponent(tool)}/call`, { token, params });
  }

  async listPendingApprovals(): Promise<ApprovalEntrySummary[]> {
    const body = await this.getJson<{ pending: ApprovalEntrySummary[] }>("/approvals");
    return body.pending;
  }

  async decide(approvalId: string, approve: boolean): Promise<{ approval_id: string; decision: string }> {
    return this.postJson(`/approvals/${encodeURIComponent(approvalId)}/decide`, { approve });
  }

  private async getJson<T>(path: string): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`);
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${await res.text()}`);
    return (await res.json()) as T;
  }

  private async postJson<T>(path: string, payload: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`POST ${path} failed: ${res.status} ${await res.text()}`);
    return (await res.json()) as T;
  }
}
