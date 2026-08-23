import { authHeaders, withAuthQuery } from "@/lib/apiAuth";

const BASE = "";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export const AUTH_REQUIRED_MESSAGE =
  "Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use.";

export function isAuthRequiredError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

async function errorFromResponse(res: Response): Promise<ApiError> {
  let detail = `HTTP ${res.status}`;
  try {
    const body = await res.json();
    detail = body.detail || body.message || detail;
  } catch { /* ignore */ }
  if (res.status === 401 || res.status === 403) {
    detail = AUTH_REQUIRED_MESSAGE;
  }
  return new ApiError(detail, res.status);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { headers, ...rest } = options ?? {};
  const mergedHeaders: Record<string, string> = { "Content-Type": "application/json", ...authHeaders() };
  if (headers) {
    new Headers(headers).forEach((value, key) => {
      mergedHeaders[key] = value;
    });
  }
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: mergedHeaders,
  });
  if (!res.ok) {
    throw await errorFromResponse(res);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : ({} as T);
}

export interface UploadResult {
  status: string;
  file_path: string;
  filename: string;
}

async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/upload`, { method: "POST", headers: authHeaders(), body: form });
  if (!res.ok) {
    throw await errorFromResponse(res);
  }
  return res.json();
}

function appendQueryParam(url: string, key: string, value: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${encodeURIComponent(key)}=${encodeURIComponent(value)}`;
}

export const api = {
  uploadFile,
  listRuns: () => request<RunListItem[]>("/runs"),
  getRun: (id: string) => request<RunData>(`/runs/${id}`),
  getRunCode: (id: string) => request<Record<string, string>>(`/runs/${id}/code`),
  getRunPine: (id: string) => request<PineScriptResult>(`/runs/${id}/pine`),
  listSessions: () => request<SessionItem[]>("/sessions"),
  createSession: (title?: string) => request<SessionItem>("/sessions", { method: "POST", body: JSON.stringify({ title: title || "" }) }),
  deleteSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "DELETE" }),
  renameSession: (sid: string, title: string) => request<{ status: string }>(`/sessions/${sid}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  sendMessage: (sid: string, content: string) => request<{ message_id: string; attempt_id: string }>(`/sessions/${sid}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  cancelSession: (sid: string) => request<{ status: string }>(`/sessions/${sid}/cancel`, { method: "POST" }),
  getSessionMessages: (sid: string) => request<MessageItem[]>(`/sessions/${sid}/messages`),
  createGoal: (sid: string, body: CreateGoalRequest) =>
    request<GoalSnapshot>(`/sessions/${sid}/goal`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getGoal: (sid: string) => request<GoalSnapshot>(`/sessions/${sid}/goal`),
  updateGoal: (sid: string, body: UpdateGoalRequest) =>
    request<UpdateGoalResponse>(`/sessions/${sid}/goal`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  addGoalEvidence: (sid: string, body: AddGoalEvidenceRequest) =>
    request<AddGoalEvidenceResponse>(`/sessions/${sid}/goal/evidence`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateGoalStatus: (sid: string, body: UpdateGoalStatusRequest) =>
    request<UpdateGoalStatusResponse>(`/sessions/${sid}/goal/status`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  sseUrl: (sid: string, options?: { replay?: "active" }) => {
    let url = withAuthQuery(`${BASE}/sessions/${sid}/events`);
    if (options?.replay) url = appendQueryParam(url, "replay", options.replay);
    return url;
  },

  // Swarm API
  listSwarmPresets: () => request<SwarmPreset[]>("/swarm/presets"),
  createSwarmRun: (preset_name: string, user_vars: Record<string, string>) =>
    request<{ id: string; status: string }>("/swarm/runs", {
      method: "POST",
      body: JSON.stringify({ preset_name, user_vars }),
    }),
  listSwarmRuns: () => request<SwarmRunSummary[]>("/swarm/runs"),
  getSwarmRun: (id: string) => request<Record<string, unknown>>(`/swarm/runs/${id}`),
  swarmSseUrl: (id: string) => withAuthQuery(`${BASE}/swarm/runs/${id}/events`),
  cancelSwarmRun: (id: string) =>
    request<{ status: string }>(`/swarm/runs/${id}/cancel`, { method: "POST" }),
  retrySwarmRun: (id: string) =>
    request<{ id: string; status: string; preset_name: string }>(`/swarm/runs/${id}/retry`, { method: "POST" }),
  getLLMSettings: () => request<LLMSettings>("/settings/llm"),
  updateLLMSettings: (settings: UpdateLLMSettingsRequest) =>
    request<LLMSettings>("/settings/llm", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  getDataSourceSettings: () => request<DataSourceSettings>("/settings/data-sources"),
  updateDataSourceSettings: (settings: UpdateDataSourceSettingsRequest) =>
    request<DataSourceSettings>("/settings/data-sources", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  // Alpha Zoo API
  listAlphas: (params: AlphaListParams = {}) => {
    const q = new URLSearchParams();
    if (params.zoo) q.set("zoo", params.zoo);
    if (params.theme) q.set("theme", params.theme);
    if (params.universe) q.set("universe", params.universe);
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<AlphaListResponse>(`/alpha/list${qs ? `?${qs}` : ""}`);
  },
  getAlpha: (alphaId: string) =>
    request<AlphaDetailResponse>(`/alpha/${encodeURIComponent(alphaId)}`),
  createAlphaBench: (body: AlphaBenchRequest) =>
    request<{ status: string; job_id: string }>("/alpha/bench", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  alphaBenchStreamUrl: (jobId: string) =>
    withAuthQuery(`${BASE}/alpha/bench/${encodeURIComponent(jobId)}/stream`),

  // Connector runtime channel — privileged surface actions (NOT agent tools).
  // commit is the ONLY action that writes a mandate; halt trips the kill switch.
  commitMandate: (body: CommitMandateRequest) =>
    request<CommitMandateResponse>("/mandate/commit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  haltLive: (session_id?: string, broker?: string, reason?: string) =>
    request<HaltLiveResponse>("/live/halt", {
      method: "POST",
      body: JSON.stringify({ session_id, broker, reason }),
    }),
  // Read the persistent runtime status across all authorized brokers (SPEC §7.5).
  // Polled by the RunnerStatus panel; a plain authenticated GET, never a chat message.
  getLiveStatus: () => request<LiveStatus>("/live/status"),
  getTradingDashboard: () => request<TradingDashboard>("/trading/dashboard"),
  getTradingDashboardSource: (name: string) =>
    request<Record<string, unknown>>(`/trading/dashboard/sources/${encodeURIComponent(name)}`),
  getTradingQuotes: (symbols: string[]) => {
    const normalized = [...new Set(symbols.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean))]
      .sort()
      .join(",");
    return request<TradingQuotesResponse>(
      `/trading/quotes?symbols=${encodeURIComponent(normalized)}`,
    );
  },
  getTradingBars: (symbol: string, tf = "5m", limit = 200) => {
    const query = new URLSearchParams({
      symbol: symbol.trim().toUpperCase(),
      tf,
      limit: String(limit),
    });
    return request<TradingBarsResponse>(`/trading/bars?${query.toString()}`);
  },
  getTradingOpportunities: () => request<LiveOpportunityReport>("/trading/opportunities"),
  getTradingFeedStatus: () => request<TradingFeedStatus>("/trading/feed-status"),
  tradingOpportunityStreamUrl: () => withAuthQuery(`${BASE}/trading/opportunities/stream`),
  authorizeLive: (broker: string) =>
    request<LiveAuthorizeResponse>("/live/authorize", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  // Start/stop the persistent runner (SPEC §7.5). Privileged surface actions, not agent tools.
  startLiveRunner: (broker: string) =>
    request<LiveRunnerResponse>("/live/runner/start", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
  stopLiveRunner: (broker: string) =>
    request<LiveRunnerResponse>("/live/runner/stop", {
      method: "POST",
      body: JSON.stringify({ broker }),
    }),
};

// --- Swarm types ---

export interface SwarmPreset {
  name: string;
  title: string;
  description: string;
  agent_count: number;
  variables: { name: string; description: string; required: boolean }[];
}

export interface SwarmRunSummary {
  id: string;
  preset_name: string;
  status: string;
  created_at: string;
  task_count: number;
  completed_count: number;
}

export interface LLMProviderOption {
  name: string;
  label: string;
  api_key_env?: string | null;
  base_url_env: string;
  default_model: string;
  default_base_url: string;
  api_key_required: boolean;
  auth_type?: string;
  login_command?: string | null;
}

export interface LLMSettings {
  provider: string;
  model_name: string;
  base_url: string;
  api_key_env?: string | null;
  api_key_configured: boolean;
  api_key_hint?: string | null;
  api_key_required: boolean;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort: string;
  sse_timeout_seconds: number;
  env_path: string;
  providers: LLMProviderOption[];
}

export interface UpdateLLMSettingsRequest {
  provider: string;
  model_name: string;
  base_url: string;
  api_key?: string;
  clear_api_key?: boolean;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort?: string;
}

export interface DataSourceSettings {
  tushare_token_configured: boolean;
  tushare_token_hint?: string | null;
  baostock_supported: boolean;
  baostock_installed: boolean;
  baostock_message: string;
  env_path: string;
}

export interface UpdateDataSourceSettingsRequest {
  tushare_token?: string;
  clear_tushare_token?: boolean;
}

// --- Types matching backend API contracts ---

export interface RunListItem {
  run_id: string;
  status: string;
  created_at: string;
  prompt?: string;
  total_return?: number;
  sharpe?: number;
  codes?: string[];
  start_date?: string;
  end_date?: string;
}

export interface PriceBar {
  time: string;
  timestamp?: string;
  code?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradeMarker {
  time: string;
  timestamp?: string;
  code?: string;
  side: "BUY" | "SELL";
  price: number;
  qty?: number;
  reason?: string;
  text?: string;
}

export interface EquityPoint {
  time: string;
  equity: string | number;
  drawdown: string | number;
}

export interface ValidationData {
  monte_carlo?: {
    actual_sharpe: number;
    actual_max_dd: number;
    p_value_sharpe: number;
    p_value_max_dd: number;
    simulated_sharpe_mean: number;
    simulated_sharpe_std: number;
    simulated_sharpe_p5: number;
    simulated_sharpe_p95: number;
    n_simulations: number;
    n_trades: number;
    error?: string;
  };
  bootstrap?: {
    observed_sharpe: number;
    ci_lower: number;
    ci_upper: number;
    median_sharpe: number;
    prob_positive: number;
    confidence: number;
    n_bootstrap: number;
    error?: string;
  };
  walk_forward?: {
    n_windows: number;
    windows: Array<{
      window: number;
      start: string;
      end: string;
      return: number;
      sharpe: number;
      max_dd: number;
      trades: number;
      win_rate: number;
    }>;
    profitable_windows: number;
    consistency_rate: number;
    return_mean: number;
    return_std: number;
    sharpe_mean: number;
    sharpe_std: number;
    error?: string;
  };
}

export interface RunData {
  status: string;
  run_id: string;
  prompt?: string;
  elapsed_seconds?: number;
  run_directory?: string;
  run_stage?: string;
  run_context?: Record<string, unknown>;

  metrics?: BacktestMetrics;
  artifacts?: ArtifactInfo[];
  run_card?: RunCard;
  validation?: ValidationData;

  price_series?: Record<string, PriceBar[]>;
  indicator_series?: Record<string, Record<string, IndicatorPoint[]>>;
  trade_markers?: TradeMarker[];
  equity_curve?: EquityPoint[];
  trade_log?: Array<Record<string, string>>;
  run_logs?: Array<{ source?: string; line_number?: number; message?: string }>;
}

export interface RunCard {
  schema_version?: string;
  generated_at?: string;
  run_dir?: string;
  backtest?: Record<string, unknown>;
  reproducibility?: Record<string, unknown>;
  data_sources?: string[];
  metrics?: Record<string, unknown>;
  validation?: unknown;
  warnings?: string[];
  artifacts?: RunCardArtifact[];
  [key: string]: unknown;
}

export interface RunCardArtifact {
  path: string;
  size_bytes: number;
  sha256: string;
}

export interface BacktestMetrics {
  final_value: number;
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe: number;
  win_rate: number;
  trade_count: number;
  [key: string]: number;
}


export interface IndicatorPoint {
  time: string;
  value: number;
}

export interface ArtifactInfo {
  name: string;
  path: string;
  type: string;
  size: number;
  exists: boolean;
}

export interface PineScriptResult {
  exists: boolean;
  content: string | null;
}

export interface SessionItem {
  session_id: string;
  title?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  last_attempt_id?: string;
}

// --- Goal types ---

export type GoalStatus =
  | "active"
  | "paused"
  | "waiting_user"
  | "needs_refresh"
  | "insufficient_evidence"
  | "compliance_blocked"
  | "blocked"
  | "budget_limited"
  | "usage_limited"
  | "complete"
  | "cancelled"
  | "superseded";

export type GoalRiskTier =
  | "research_general"
  | "market_specific_short_term"
  | "personalized_advice_or_position_sizing";

export interface GoalRecord {
  goal_id: string;
  session_id: string;
  status: GoalStatus;
  objective: string;
  ui_summary: string;
  source: string;
  protocol: string;
  risk_tier: GoalRiskTier;
  token_budget?: number | null;
  tokens_used: number;
  turn_budget?: number | null;
  turns_used: number;
  time_budget_seconds?: number | null;
  time_used_seconds: number;
  budget_wrapup_sent: boolean;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  recap?: string | null;
}

export interface GoalClaim {
  claim_id: string;
  goal_id: string;
  session_id: string;
  claim_type: string;
  text: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface GoalCriterion {
  criterion_id: string;
  goal_id: string;
  session_id: string;
  text: string;
  required: boolean;
  status: string;
  freshness_requirement?: string | null;
  protocol_step?: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalEvidence {
  evidence_id: string;
  goal_id: string;
  session_id: string;
  text: string;
  criterion_id?: string | null;
  claim_id?: string | null;
  evidence_type: string;
  tool_call_id?: string | null;
  run_id?: string | null;
  source_provider?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  symbol_universe: string[];
  benchmark: string[];
  timeframe?: string | null;
  method?: string | null;
  assumptions: Record<string, unknown>;
  artifact_path?: string | null;
  artifact_hash?: string | null;
  retrieved_at: string;
  data_as_of?: string | null;
  freshness_status: string;
  verification_status: string;
  confidence?: string | null;
  caveat?: string | null;
  contradicts_claim_ids: string[];
  created_at: string;
}

export interface GoalSnapshot {
  goal: GoalRecord;
  claims: GoalClaim[];
  criteria: GoalCriterion[];
  evidence: GoalEvidence[];
  evidence_count: number;
}

export interface CreateGoalRequest {
  objective: string;
  criteria?: string[];
  ui_summary?: string;
  protocol?: string;
  risk_tier?: GoalRiskTier;
  token_budget?: number;
  turn_budget?: number;
  time_budget_seconds?: number;
}

export interface AddGoalEvidenceRequest {
  goal_id: string;
  expected_goal_id: string;
  text: string;
  criterion_id?: string | null;
  claim_id?: string | null;
  evidence_type?: string;
  tool_call_id?: string | null;
  run_id?: string | null;
  source_provider?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  symbol_universe?: string[];
  benchmark?: string[];
  timeframe?: string | null;
  method?: string | null;
  assumptions?: Record<string, unknown>;
  artifact_path?: string | null;
  artifact_hash?: string | null;
  data_as_of?: string | null;
  confidence?: string | null;
  caveat?: string | null;
  contradicts_claim_ids?: string[];
}

export interface UpdateGoalRequest {
  goal_id: string;
  expected_goal_id: string;
  objective?: string;
  ui_summary?: string;
}

export interface UpdateGoalResponse {
  goal: GoalRecord;
  snapshot: GoalSnapshot;
}

export interface AddGoalEvidenceResponse {
  evidence: GoalEvidence;
  snapshot: GoalSnapshot;
}

export interface GoalAuditRowRequest {
  criterion_id: string;
  result: string;
  evidence_ids?: string[];
  notes?: string;
}

export interface UpdateGoalStatusRequest {
  goal_id: string;
  expected_goal_id: string;
  status: GoalStatus;
  audit?: GoalAuditRowRequest[];
  recap?: string | null;
}

export interface UpdateGoalStatusResponse {
  goal: GoalRecord;
  snapshot: GoalSnapshot;
}

// --- Alpha Zoo types ---

export interface AlphaListParams {
  zoo?: string;
  theme?: string;
  universe?: string;
  limit?: number;
}

export interface AlphaSummary {
  id: string;
  zoo: string;
  theme: string[];
  universe: string[];
  nickname?: string;
  decay_horizon?: number | null;
  min_warmup_bars?: number | null;
  requires_sector?: boolean;
}

export interface AlphaListResponse {
  status: string;
  alphas: AlphaSummary[];
  total: number;
  returned: number;
  truncated: boolean;
}

export interface AlphaDetail {
  id: string;
  zoo: string;
  module_path?: string;
  meta: Record<string, unknown>;
}

export interface AlphaDetailResponse {
  status: string;
  alpha: AlphaDetail;
  source_code: string;
}

export interface AlphaBenchRequest {
  zoo: string;
  universe: string;
  period: string;
  top?: number;
}

export interface AlphaBenchTopRow {
  id: string;
  ic_mean: number;
  ir: number;
  theme: string[];
  formula_latex: string;
  category: "alive" | "reversed" | "dead";
}

export interface AlphaBenchResult {
  alive: number;
  reversed: number;
  dead: number;
  skipped?: number;
  top5_by_ir: AlphaBenchTopRow[];
  dead_examples: AlphaBenchTopRow[];
  by_theme: Record<string, { alive: number; reversed: number; dead: number }>;
}

// --- Connector runtime channel types ---

/** One mandate profile inside a `mandate.proposal` event (SPEC Consent §1). */
export interface MandateProfile {
  ordinal: number;
  label: string;
  /** Concrete ticker list, or a structural universe descriptor (e.g. "tech_sector"). */
  universe: string[] | string;
  max_order_usd: number;
  daily_trade_cap: number;
  /** "none" for cash-only, otherwise a leverage descriptor/multiple. */
  leverage: string | number;
  instruments: string[];
  notes?: string;
}

/** Account block of a `mandate.proposal` event. */
export interface MandateProposalAccount {
  broker: string;
  type: string;
  funded_by: string;
}

/** Payload of the `mandate.proposal` SSE event (SPEC Consent §1). */
export interface MandateProposal {
  type?: string;
  proposal_id: string;
  session_id?: string;
  intent_normalized?: string;
  account?: MandateProposalAccount;
  ceilings_ref?: string;
  profiles: MandateProfile[];
  funding_note?: string;
  halt_note?: string;
  /** Present only when this proposal was triggered by a mandate breach (SPEC Consent §3). */
  reauth_for?: { breach_id?: string } | null;
}

/** Payload of the `mandate.committed` SSE event (SPEC Consent §1 COMMIT). */
export interface MandateCommitted {
  proposal_id?: string;
  mandate_id?: string;
  consent_record_id?: string;
  selected_ordinal?: number;
  broker?: string;
  /** Resolved limits, surfaced for the compact active-mandate badge. */
  max_order_usd?: number;
  daily_trade_cap?: number;
  expires_at?: string;
}

/** Payload of the `live.halted` SSE event (SPEC Consent §4). */
export interface LiveHalted {
  broker?: string | null;
  tripped_at?: string;
  by?: string;
  reason?: string;
}

/** Payload of the `live.action` SSE event (SPEC Consent §5 audit notify). */
export interface LiveAction {
  audit_id?: string;
  ts?: string;
  kind: string;
  intent_normalized?: string;
  outcome?: string;
  broker?: string;
  remote_tool?: string;
  error?: string | null;
}

export interface CommitMandateRequest {
  broker: string;
  proposal_id: string;
  selected_ordinal: number;
  /** Present only on the adjust path (SPEC Consent §3); null otherwise. */
  adjustments?: Record<string, unknown> | null;
  /** Explicit affirmative consent; the surface sets it on the user's click. */
  consent_ack: boolean;
  session_id?: string;
  account_ref?: string;
  lifetime_days?: number;
}

export interface CommitMandateResponse {
  mandate_id: string;
  consent_record_id: string;
  selected_ordinal?: number;
  broker?: string;
  max_order_usd?: number;
  daily_trade_cap?: number;
  expires_at?: string;
}

export interface HaltLiveResponse {
  halted: boolean;
  broker?: string | null;
  reason: string;
  sentinel: string;
}

export interface LiveAuthorizeRequest {
  broker: string;
}

export interface LiveAuthorizeResponse {
  broker: string;
  connector_profile: string;
  oauth_token_present: boolean;
  instruction: string;
  note?: string;
}

/** Mandate limits surfaced inside a `GET /live/status` broker entry (SPEC §7.5). */
export interface LiveMandateLimits {
  max_order_notional_usd?: number;
  max_total_exposure_usd?: number;
  max_leverage?: number;
  max_trades_per_day?: number;
  allowed_instruments?: string[];
  account_funding_usd?: number;
  [key: string]: unknown;
}

/** Active mandate block of a `GET /live/status` broker entry. */
export interface LiveMandateStatus {
  broker?: string;
  mandate_id?: string;
  account_ref?: string;
  created_at?: string;
  limits?: LiveMandateLimits;
  /** ISO timestamp the mandate auto-expires (SPEC §7.5 #7 proactive expiry). */
  expires_at?: string;
  expires_in_seconds?: number | null;
  expired?: boolean;
}

/** Runner liveness block of a `GET /live/status` broker entry (SPEC §7.5 #3). */
export interface LiveRunnerLiveness {
  broker?: string;
  alive: boolean;
  /** Unix epoch seconds of the last heartbeat tick; null if the runner never started. */
  last_tick?: number | string | null;
  last_tick_age_seconds?: number | null;
}

export interface LiveBrokerAuthStatus {
  broker: string;
  oauth_token_present: boolean;
  is_live_broker: boolean;
}

/** One broker entry in the `GET /live/status` response. */
export interface LiveBrokerStatus {
  auth: LiveBrokerAuthStatus;
  mandate?: LiveMandateStatus | null;
  runner: LiveRunnerLiveness;
  halted: boolean;
}

/** Response of `GET /live/status` (SPEC §7.5 runner status panel + C2). */
export interface LiveStatus {
  brokers: LiveBrokerStatus[];
  global_halted: boolean;
}

export interface TradingCandidate {
  plan_id?: string;
  symbol: string;
  asset_class: string;
  source: string;
  setup: string;
  direction: string;
  status: string;
  lane: string;
  source_score: number | null;
  routing_priority: number;
  paper_consumable: boolean;
  entry: number | null;
  stop: number | null;
  target: number | null;
  reward_risk: number | null;
  instrument: string;
  order_style: string;
  blockers: string[];
  reasons: string[];
  evidence: Record<string, unknown>;
  generated_at?: string | null;
  setup_score?: number;
  setup_grade?: string;
  timing_score?: number;
  execution_score?: number;
  decision_score?: number;
  grade?: string;
  score_label?: string;
  lifecycle?: "confirmed" | "armed" | "too_late" | "invalid" | "research_only";
  actionability?: "shadow_ready" | "wait" | "late_no_chase" | "invalid" | "research_only";
  next_action?: string;
  instrument_status?: string;
  current_price?: number | null;
  move_consumed_pct?: number | null;
  reward_remaining_r?: number | null;
  confirmation_state?: string | null;
  probability?: {
    value: number | null;
    status: string;
    label: string;
    sample_size: number | null;
    lower_bound?: number | null;
    independent_dates?: number | null;
    brier_skill_vs_expanding_base_rate?: number | null;
    calibration_qualified?: boolean;
    ranking_eligible?: boolean;
    qualification_failures?: string[];
  };
  probability_source?: {
    provider?: string | null;
    generated_at?: string | null;
    bucket_id?: string | null;
    method?: string | null;
    execution_enabled: false;
    can_submit_orders: false;
  };
  factors?: Record<string, {
    score: number | null;
    grade: string;
    available: boolean;
    reason: string;
  }>;
  trade_plan?: {
    instrument: string;
    contract?: {
      symbol: string;
      underlying: string;
      expiry: string;
      right: string;
      strike: number;
      expired: boolean;
    } | null;
    underlying_price: number | null;
    entry_trigger: number | null;
    entry_instruction: string;
    invalidation: number | null;
    targets: Array<{ name: string; price: number }>;
    reward_risk: number | null;
    time_window: string;
    risk_note: string;
  };
}

export interface TradingSource {
  name: string;
  filename: string;
  path?: string;
  line_reference?: number | null;
  report_hash?: string | null;
  spec_hash?: string | null;
  available: boolean;
  generated_at: string | null;
  age_seconds: number | null;
  freshness: "live" | "recent" | "prior_session" | "stale" | "missing" | "clock_skew";
  clock_skew_seconds?: number;
  provider?: string | null;
  mode?: string | null;
  execution_enabled: boolean;
  can_submit_orders: boolean;
}

export interface SimplePriceActionSignal {
  symbol: string;
  state: "CONFIRMED" | "WAIT" | "INVALID";
  color: "GREEN" | "YELLOW" | "RED";
  direction: "LONG" | "SHORT" | "NEUTRAL";
  grade: string;
  score: number;
  setup: string;
  trigger: number | null;
  stop: number | null;
  target: number | null;
  last_price: number | null;
  decisive_reason: string;
  action: string;
  failed_quality_gates: string[];
  bar_completed_at?: string | null;
  score_definition: string;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingEvidenceSource {
  source: string;
  filename?: string | null;
  path?: string | null;
  line_reference?: number | null;
  report_hash?: string | null;
  spec_hash?: string | null;
  provider: string | null;
  mode: string | null;
  generated_at: string | null;
  age_seconds: number | null;
  freshness: TradingSource["freshness"];
  available: boolean;
  provenance_qualified: boolean;
  data: Record<string, unknown>;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingEvidenceAuthority {
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingRetroEvidence extends TradingEvidenceAuthority {
  daily_eod: TradingEvidenceSource;
  daily_outcome: TradingEvidenceSource;
  aplus_review: TradingEvidenceSource;
  closed_postmortem: TradingEvidenceSource;
  missed_banger: TradingEvidenceSource;
}

export interface TradingJournalEvidence extends TradingEvidenceAuthority {
  rejected_intel: TradingEvidenceSource;
  lesson_ledger: TradingEvidenceSource;
  needs_review: TradingEvidenceSource;
}

export interface TradingSocialEvidence extends TradingEvidenceAuthority {
  verified_trader: TradingEvidenceSource;
  public_intake: TradingEvidenceSource;
  trending_symbols: TradingEvidenceSource;
}

export interface TradingCatalystsToday {
  source: "catalysts";
  provider: string | null;
  mode: string | null;
  generated_at: string | null;
  age_seconds: number | null;
  freshness: TradingSource["freshness"];
  days: Array<Record<string, unknown> & {
    execution_enabled: false;
    can_submit_orders: false;
  }>;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingOptionsContext {
  status: "context_available" | "unavailable";
  completeness: "complete" | "partial" | "unavailable";
  surface: TradingEvidenceSource;
  heatmap: TradingEvidenceSource;
  vol_premium: TradingEvidenceSource;
  feed_qualification?: TradingEvidenceSource;
  manual_execution_reference_available?: boolean;
  price_discovery_qualified_count?: number;
  reason: string;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingMarketDataSource {
  provider: "alpaca";
  feed: "iex";
  label: "alpaca_iex_latest_quote" | "alpaca_iex_bars";
}

export interface TradingQuotesResponse {
  generated_at: string;
  source: TradingMarketDataSource;
  quotes: Record<string, TradingQuote>;
  cache: "hit" | "miss" | "stale_fallback";
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingQuote {
  price: number | null;
  bid: number | null;
  ask: number | null;
  ts: string | null;
  freshness: "live" | "recent" | "stale" | "missing";
  stale: boolean;
  source: "alpaca_iex_latest_quote";
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export interface TradingBarsResponse {
  generated_at: string;
  symbol: string;
  tf: string;
  source: TradingMarketDataSource;
  source_timestamp: string | null;
  freshness: "live" | "recent" | "stale" | "missing";
  bars: TradingBar[];
  cache: "hit" | "miss" | "stale_fallback";
  execution_enabled: false;
  can_submit_orders: false;
}

export interface LiveOpportunityFeed {
  provider: "alpaca";
  feed: "iex" | "sip";
  transport: "websocket" | "rest_polling";
  entitlement: string;
  label?: string;
  last_event_at?: string | null;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface MarketStructurePattern {
  pattern_id: string;
  family?: string;
  complexity: "simple" | "intermediate" | "advanced" | "anti_pattern";
  direction: "bullish" | "bearish" | "neutral" | string;
  confidence_score: number;
  trigger_state: "confirmed" | "waiting_retest" | "waiting_neckline" | string;
  reason: string;
  trigger: number | null;
  invalidation: number | null;
  reference_level: number | null;
  closed_bar_only: true;
  execution_enabled?: false;
  can_submit_orders?: false;
  model_sequence?: {
    model_version: string;
    core_complete: boolean;
    chronology_valid: boolean;
    mapped_execution_timeframe: string;
    stages: Array<{
      name: "htf_fvg_context" | "third_candle_range" | "liquidity_sweep" | "ifvg" | "cisd" | string;
      status: "complete" | "pending" | "missing" | string;
      body_close_required?: boolean;
      [key: string]: unknown;
    }>;
    bonus_confluences: {
      displacement: boolean;
      liquidity_sweep: boolean;
      smt: boolean | string;
      consequent_encroachment?: {
        level: number | null;
        status: string;
      };
    };
    probability_status: string;
    source_label: string;
    execution_enabled: false;
    can_submit_orders: false;
  };
}

export interface PatternGrade {
  rubric_version: "pattern_grade_v1" | string;
  components: {
    base_rate: number;
    volume_rvol: number;
    mtf_alignment: number;
    regime_fit: number;
    confluence: number;
    reward_risk: number;
  };
  weights: Record<string, number>;
  raw_score: number;
  penalty_factors: {
    anti_pattern: number;
    macro_window: number;
    wide_spread: number;
    stale_feed: number;
  };
  penalty_multiplier: number;
  final_score: number;
  grade: "A" | "B" | "C" | "D";
  label: string;
  all_observed_conditions_aligned: boolean;
  validation_status: "LOCAL_FORWARD_VALIDATED" | "RESEARCH_PRIOR" | "UNCALIBRATED" | string;
  evidence: Record<string, string>;
  warnings: string[];
  execution_enabled: false;
  can_submit_orders: false;
}

export interface MarketStructureEntryPlan {
  status: "actionable_manual_review" | "conditional" | "unavailable" | string;
  timeframe?: string;
  trigger: number | null;
  entry_zone: { low: number | null; high: number | null };
  invalidation: number | null;
  risk_per_share?: number | null;
  instruction: string;
}

export interface MarketStructureExitPlan {
  status: "defined" | "unavailable" | string;
  targets: Array<{ name: string; price: number | null; reward_risk?: number }>;
  time_stop_bars: number | null;
  time_stop?: { bars: number; timeframe: string; minutes: number; status: string } | null;
  management: string;
}

export interface TimeframeCoverageRow {
  timeframe: string;
  role: string;
  minimum_bars: number;
  completed_bars: number;
  status: string;
  provenance: string;
  required_for_aplus: boolean;
}

export interface TimeframeCoverage {
  status: string;
  missing_required: string[];
  frames: TimeframeCoverageRow[];
  closed_bar_only: true;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TimeframeScanRow {
  timeframe: string;
  role: string;
  completed_bars: number;
  trend: { bias?: string; strength?: number; [key: string]: unknown };
  best_setup: Partial<MarketStructurePattern> | null;
  worst_setup: Partial<MarketStructurePattern> | null;
  source_label: string;
  provenance?: string;
  score_effect?: string;
  closed_bar_only: true;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TimeframePlan {
  primary_trigger: string;
  execution_refinement: string;
  confirmation: string[];
  structure: string[];
  regime: string[];
  coverage_status: string;
  closed_bar_only: true;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface LiquidityReferenceLevel {
  id: string;
  label: string;
  price: number;
  side: "buy_side" | "sell_side" | string;
  source_label: string;
  freshness: string;
  historical_probability: { status: string; value: number | null };
  execution_enabled: false;
  can_submit_orders: false;
}

export interface LiquidityLevelContext {
  status: "available" | "unavailable" | string;
  levels: LiquidityReferenceLevel[];
  active_sweeps: Array<{ level_id: string; level_label?: string; direction: string; status: string }>;
  probability_status: string;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface ParticipationContext {
  status: string;
  direction: string;
  method: "ohlcv_participation_curvature_proxy_v1" | string;
  true_order_flow: false;
  score: number | null;
  curvature_proxy?: number;
  reason: string;
  probability: { status: string; value: number | null };
  source_labels: string[];
  execution_enabled: false;
  can_submit_orders: false;
}

export interface MacroTimingContext {
  status: "context_only_unvalidated" | string;
  active_window: string | null;
  active: boolean;
  label: string;
  source_label: string;
  score_effect: string;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface StratContext {
  status: string;
  current_scenario: "1" | "2u" | "2d" | "3" | null;
  sequence: string[];
  ftfc: {
    state: "bullish" | "bearish" | "conflict" | "incomplete" | "unavailable" | string;
    strict: boolean;
    frame_count: number;
    frames: Record<string, string>;
  };
  magnitude: { direction: string; target_label: string | null; target: number | null };
  probability: { status: string; value: number | null };
  score_effect: "none_until_local_validation" | string;
  source_labels: string[];
  closed_bar_only?: true;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface NyBalanceRangeContext {
  status: string;
  range: { high: number; low: number; bar_count: number } | null;
  first_sweep: { side: string; timestamp: string } | null;
  cisd: { direction: string | null; confirmed: boolean } | null;
  target: number | null;
  historical_probability: { status: string; value: number | null };
  external_claim_status: "excluded_until_independently_reproduced" | string;
  source_labels: string[];
  closed_bar_only?: true;
  score_effect?: string;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface MarketStructureAnalysis {
  schema_version?: number;
  decision: "READY_TO_REVIEW" | "WAIT" | "REJECT" | "STAND_ASIDE";
  grade: string;
  score: number;
  pattern_grade?: PatternGrade;
  structure_regime?: string;
  best_setup: MarketStructurePattern | null;
  worst_setup: MarketStructurePattern | null;
  positive_patterns?: MarketStructurePattern[];
  negative_patterns?: MarketStructurePattern[];
  entry_plan: MarketStructureEntryPlan;
  exit_plan: MarketStructureExitPlan;
  hard_blockers: string[];
  timeframe_alignment: {
    state: "aligned" | "mixed" | "conflict" | "unavailable" | string;
    frames: Record<string, Record<string, unknown>>;
    closed_bar_only: true;
  };
  timeframe_coverage?: TimeframeCoverage;
  timeframe_scan?: TimeframeScanRow[];
  timeframe_plan?: TimeframePlan;
  liquidity_level_context?: LiquidityLevelContext;
  participation_context?: ParticipationContext;
  macro_context?: MacroTimingContext;
  strat_context?: StratContext;
  ny_0800_0900_range_context?: NyBalanceRangeContext;
  freshness: "live" | "recent" | "stale" | "missing" | string;
  source_labels: string[];
  factor_scores?: Record<string, number | null>;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface MarketStructureWatchRow extends Omit<MarketStructureAnalysis, "schema_version" | "structure_regime" | "positive_patterns" | "negative_patterns" | "factor_scores"> {
  symbol: string;
}

export interface LiveOpportunityCandidate {
  candidate_id: string;
  symbol: string;
  asset_class: "equity";
  setup_family: string;
  direction: "bullish" | "bearish" | string;
  reason: string;
  decision_score: number;
  grade: string;
  score_basis?: string;
  state: "READY_TO_REVIEW" | "WATCH" | "REJECT";
  freshness: "live" | "recent" | "stale" | "missing";
  entry: number | null;
  invalidation: number | null;
  targets: Array<{ name: string; price: number }>;
  reward_risk_after_friction: number | null;
  rvol_time_of_day?: number | null;
  session_dollar_volume?: number | null;
  average_dollar_volume?: number | null;
  relative_strength_vs_market_sector?: number | null;
  source_labels: string[];
  blockers: string[];
  catalyst?: Record<string, unknown> | null;
  quote?: Record<string, unknown>;
  factor_scores?: Record<string, number>;
  market_structure?: MarketStructureAnalysis;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface LiveOpportunityReport {
  schema_version: 1;
  generated_at: string;
  mode: string;
  decision_state: "READY_TO_REVIEW" | "STAND_ASIDE";
  ready_count: number;
  candidate_count: number;
  setup_families: string[];
  market_structure_patterns?: Array<{
    id: string;
    family?: string;
    complexity: "simple" | "intermediate" | "advanced" | "anti_pattern";
    role: "setup" | "confirmation" | "veto" | string;
    confirmation: string;
  }>;
  market_structure_watchlist?: MarketStructureWatchRow[];
  feed: LiveOpportunityFeed;
  candidates: LiveOpportunityCandidate[];
  top_candidates: LiveOpportunityCandidate[];
  warnings?: string[];
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingFeedStatus {
  generated_at: string;
  configured: LiveOpportunityFeed;
  last_report_at: string | null;
  last_event_at: string | null;
  stream_status: string;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface CalibrationReliabilityBin {
  count: number;
  mean_probability: number;
  observed_rate: number;
  gap: number;
}

export interface GradeCalibrationBucket {
  bucket_id: string;
  setup_family: string;
  regime: string;
  grade: string;
  probability: {
    value: number | null;
    lower_bound: number | null;
    upper_bound?: number | null;
    sample_size: number;
    independent_dates: number;
    status: "local_forward_validated" | "display_calibrated" | "not_calibrated" | string;
    label: string;
    brier_skill_vs_expanding_base_rate: number | null;
    ece: number | null;
    mce: number | null;
  };
  calibration_status: string;
  reliability_bins: CalibrationReliabilityBin[];
  execution_enabled: false;
  can_submit_orders: false;
}

export interface GradeProbabilityCalibration {
  schema_version?: number;
  provider?: string;
  generated_at?: string;
  outcome_cutoff?: string;
  method?: string;
  eligible_outcomes?: number;
  skipped_outcomes?: number;
  buckets?: GradeCalibrationBucket[];
  source?: TradingSource | Record<string, unknown>;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface DetectionPatternStat {
  pattern_id?: string;
  family: string;
  ground_truth_labeled: number;
  grader_detected: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  precision: number | null;
  recall: number | null;
  coverage_delta: number | null;
  outcome_quality?: {
    resolved_outcomes: number;
    wins: number;
    observed_win_rate: number | null;
    average_r: number | null;
  };
}

export interface DetectionPatternCoverage {
  status: string;
  metrics_qualified: boolean;
  pattern_metrics_qualified?: boolean;
  source_labels: string[];
  totals: {
    ground_truth_labeled: number;
    grader_detected: number;
    true_positives: number;
    coverage_delta: number | null;
  };
  opportunity_coverage?: {
    metrics_qualified: boolean;
    ground_truth_moves: number;
    detected_events: number;
    true_positives: number;
    false_positives: number;
    false_negatives: number;
    precision: number | null;
    recall: number | null;
    coverage_delta: number | null;
  };
  per_pattern: DetectionPatternStat[];
  per_family: DetectionPatternStat[];
  cisd_hypothesis: {
    pattern_id: "ict_cisd_universal_model";
    n_outcomes: number;
    n_dates: number;
    brier: number | null;
    scored_outcomes: number;
    status: string;
  };
  execution_enabled: false;
  can_submit_orders: false;
}

export interface CisdPromotionStatus {
  schema_version: number;
  pattern_id: "ict_cisd_universal_model";
  hypothesis_status: "unvalidated_pattern_hypothesis" | "validated_pattern";
  n_outcomes: number;
  n_unique_dates: number;
  wins: number;
  win_rate_raw: number | null;
  wilson_lower_bound_95: number | null;
  n_scored_probabilities: number;
  brier_score: number | null;
  brier_baseline: number | null;
  brier_skill: number | null;
  gate_status: "pending" | "passed";
  gate_reasons_pending: string[];
  eligible_for_validated_promotion: boolean;
  last_updated_utc: string;
  source_labels: string[];
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingDailyReviewGate {
  status: "complete" | "attention_required" | "missing" | string;
  date: string | null;
  generated_at: string | null;
  source?: TradingSource | Record<string, unknown>;
  reviewed_setup_count: number;
  outcome_followup_count: number;
  source_coverage_pct: number | null;
  overall_review_coverage_pct: number | null;
  failed_sources: string[];
  message: string;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingReadinessGate {
  id: string;
  ready: boolean;
  reason: string;
  generated_at: string | null;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingSystemReadiness {
  build: { status: string; percent: number; gates: TradingReadinessGate[] };
  runtime: { status: string; percent: number; gates: TradingReadinessGate[] };
  evidence: {
    status: "qualified" | "collecting" | string;
    ranking_qualified_bucket_count: number;
    eligible_outcomes: number;
    independent_dates: number;
    message: string;
  };
  ready_for_manual_review: boolean;
  probability_claims_qualified: boolean;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingExecutionQuality {
  status: "available" | "followup_required" | "missing" | string;
  manual: TradingSource;
  broker: TradingSource;
  manual_observations: number;
  manual_followups: number;
  broker_fills: number;
  broker_matched: number;
  broker_linkage_issues: number;
  message: string;
  execution_enabled: false;
  can_submit_orders: false;
}

export interface TradingDashboard {
  schema_version: 11;
  generated_at: string;
  refresh_seconds: number;
  mode: string;
  authority: {
    execution_enabled: boolean;
    can_submit_orders: boolean;
    live_capital_enabled: boolean;
    paper_signal_count: number;
    message: string;
  };
  headline: {
    best_setup: TradingCandidate | null;
    state: string;
    message: string;
  };
  ranking_policy?: {
    mode: "conditional_probability_first" | "decision_quality_fallback_no_qualified_probability" | string;
    qualified_candidate_count: number;
    minimum_samples: number;
    minimum_independent_dates: number;
    requires_positive_brier_skill_vs_expanding_base_rate: boolean;
    uses_conservative_lower_bound: boolean;
    fallback: string;
    execution_enabled: false;
    can_submit_orders: false;
  };
  command_card?: {
    state: "READY_TO_REVIEW" | "WAIT" | "NO_CHASE" | "INVALID" | "RESEARCH_ONLY" | "STAND_ASIDE";
    color: "GREEN" | "YELLOW" | "RED";
    symbol: string | null;
    direction: string;
    setup: string | null;
    grade: string;
    decision_score: number | null;
    trigger: number | null;
    confirmation_required: string;
    invalidation: number | null;
    target: number | null;
    instrument: string | null;
    no_trade_zone: {
      status: "available" | "not_supplied";
      low: number | null;
      high: number | null;
      instruction: string;
    };
    next_action: string;
    evidence_fresh: boolean;
    evidence_age_seconds: number | null;
    plan_id: string | null;
    execution_enabled: false;
    can_submit_orders: false;
  };
  daily_review_gate?: TradingDailyReviewGate;
  system_readiness?: TradingSystemReadiness;
  execution_quality?: TradingExecutionQuality;
  dealer_regime?: {
    status: "context_available" | "unavailable";
    source_status: string;
    net_gex_state: "negative" | "positive" | "unavailable";
    spot_vs_flip: "unavailable";
    quadrant: null;
    strategy_route: string;
    reason: string;
    execution_authority: false;
  };
  options_context: TradingOptionsContext;
  decision_desk?: {
    state_definitions: Record<string, string>;
    counts: Record<string, number>;
    best_now: TradingCandidate[];
    next_up: TradingCandidate[];
    no_chase: TradingCandidate[];
    invalid: TradingCandidate[];
    method: string;
  };
  market: {
    classification?: string | null;
    force_score?: number | null;
    confidence?: number | null;
    risk_veto?: Record<string, unknown>;
    breadth_status?: string | null;
    pct_above_50dma?: number | null;
    sector_leadership?: string | null;
    leading_sectors: string[];
    high_impact_days_ahead: unknown[];
    warnings: string[];
  };
  account: Record<string, number>;
  portfolio: Record<string, unknown> & {
    open_trades?: Record<string, { total?: number; open?: number; closed?: number }>;
    position_integrity?: Record<string, unknown>;
  };
  operations: {
    health: Record<string, number | string>;
    status?: string | null;
    signal_stack_summary: Record<string, unknown>;
    task_count: number;
    tasks: Array<Record<string, unknown>>;
    audit_issue_count: number;
    risk_blockers: string[];
    stale_source_count: number;
    stale_sources: string[];
    quarantined_sources: Array<{
      name: string;
      freshness: string;
      reason: string;
      source_label: string;
      execution_enabled: false;
      can_submit_orders: false;
    }>;
    failure_taxonomy_week: Record<string, number>;
    reconciliation_status: {
      last_run_at: string | null;
      diff_count_24h: number;
      last_diff_at: string | null;
      status: string;
    };
  };
  evidence: {
    shadow_consensus: Record<string, unknown>;
    shadow_audit: Record<string, unknown>;
    bottom_reversal: Record<string, unknown>;
    scanner_leadership: Array<Record<string, unknown>>;
    exit_accountability: Array<Record<string, unknown>>;
    move_coverage?: Record<string, unknown>;
    retro: TradingRetroEvidence;
    journal: TradingJournalEvidence;
    social: TradingSocialEvidence;
    catalysts_today: TradingCatalystsToday;
    sec_catalysts?: TradingEvidenceSource;
  };
  discovery?: {
    coverage: {
      unique_symbols_discovered?: number;
      snapshot_symbols?: number;
      symbols_with_5m_bars?: number;
      symbols_evaluated?: number;
      precision_watch_count?: number;
      filtered_count?: number;
      snapshot_coverage_pct?: number;
      source_counts?: Record<string, number>;
    };
    health?: string | null;
    session_status?: string | null;
    top_precision_watches: Array<Record<string, unknown>>;
    move_coverage: {
      movers_audited?: number;
      detected_any_stage?: number;
      detection_recall_pct?: number | null;
      classification_counts?: Record<string, number>;
      radar_snapshots_reviewed?: number;
    };
    scorecard_rolling?: {
      schema_version: number;
      generated_at: string;
      sessions: number;
      metrics: {
        recall_at_10: number | null;
        precision_at_10_mean: number | null;
        ground_truth_count: number;
        root_cause_coverage: number | null;
      };
      top_missed_moves: Array<Record<string, unknown>>;
      daily: Array<Record<string, unknown>>;
      pattern_coverage?: DetectionPatternCoverage;
      execution_enabled: false;
      can_submit_orders: false;
    };
    cisd_promotion_status?: CisdPromotionStatus;
    pattern_grader?: {
      schema_version?: number;
      provider?: string;
      generated_at?: string;
      summary?: Record<string, unknown>;
      scan_reconciliation?: Record<string, unknown>;
      latest_detections?: Array<Record<string, unknown>>;
      source?: TradingSource | Record<string, unknown>;
      execution_enabled: false;
      can_submit_orders: false;
    };
    execution_enabled?: false;
    can_submit_orders?: false;
  };
  calibration?: GradeProbabilityCalibration;
  research_governance?: {
    tested_this_week: number;
    rejected_this_week: number;
    bonferroni_denominator: number;
    effective_alpha: number | null;
    status: string;
    provenance: Array<{ path: string; line_reference: number | null }>;
    execution_enabled: false;
    can_submit_orders: false;
  };
  live_opportunities?: {
    generated_at: string | null;
    decision_state: "READY_TO_REVIEW" | "STAND_ASIDE";
    ready_count: number;
    candidate_count: number;
    feed: Partial<LiveOpportunityFeed>;
    providers?: Record<string, unknown>;
    validation?: Record<string, unknown>;
    top_candidates: LiveOpportunityCandidate[];
    market_structure_patterns?: LiveOpportunityReport["market_structure_patterns"];
    market_structure_watchlist?: MarketStructureWatchRow[];
    execution_enabled: false;
    can_submit_orders: false;
  };
  simple_signals?: {
    definitions: Record<string, string>;
    counts: Record<string, number>;
    signals: SimplePriceActionSignal[];
    generated_at?: string | null;
    execution_enabled: false;
    can_submit_orders: false;
  };
  trade_board?: {
    score_definition: string;
    probability_policy: string;
    stocks: TradingCandidate[];
    options: TradingCandidate[];
    futures: TradingCandidate[];
    review_fields: string[];
  };
  candidates: TradingCandidate[];
  sources: TradingSource[];
  warnings: string[];
}

/** Response of `POST /live/runner/start|stop`. */
export interface LiveRunnerResponse {
  broker: string;
  started?: boolean;
  already_running?: boolean;
  stopped?: boolean;
  was_running?: boolean;
}

export interface MessageItem {
  message_id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
  linked_attempt_id?: string;
  metadata?: Record<string, unknown>;
}
