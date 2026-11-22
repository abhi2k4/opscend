/**
 * Opscend API contract.
 *
 * This file is the single source of truth for the JSON the API returns.
 * The FastAPI response models in api/app/schemas.py mirror it field for field.
 * All timestamps are ISO-8601 UTC strings. All ids are strings.
 */

export type Provider = "vercel" | "railway" | "github" | (string & {});

export type Capability =
  | "LIST_SERVICES"
  | "LIST_DEPLOYS"
  | "BUILD_LOGS"
  | "RUNTIME_LOGS"
  | "WEBHOOKS"
  | "COMMITS"
  | "COMMIT_DIFF";

export type DeployStatus = "queued" | "building" | "ready" | "failed" | "canceled";
export type LogLevel = "debug" | "info" | "warn" | "error";
export type LogKind = "build" | "runtime";
export type HealthState = "up" | "down" | "unknown";
export type Confidence = "low" | "medium" | "high";

// ───────────────────────────── system / auth

export interface SystemInfo {
  version: string;
  demo_mode: boolean;
  ai: { provider: string; model: string; configured: boolean };
  queue: "arq" | "inline";
  database: "postgresql" | "sqlite";
}

export interface User {
  id: string;
  email: string;
}

// ───────────────────────────── integrations

/** One entry per adapter known to the provider registry (connected or not). */
export interface ProviderManifest {
  provider: Provider;
  name: string;
  description: string;
  /** "available" adapters can be connected today; "planned" are roadmap placeholders. */
  availability: "available" | "planned";
  capabilities: Capability[];
  /** What the user pastes, e.g. "Personal access token". */
  token_label: string;
  token_help_url: string | null;
  /** Extra non-secret config fields the adapter needs, e.g. team id. */
  config_fields: { key: string; label: string; required: boolean; placeholder: string }[];
  webhook_path: string | null;
}

export interface Integration {
  id: string;
  provider: Provider;
  account_name: string | null;
  status: "connected" | "error" | "pending";
  status_detail: string | null;
  capabilities: Capability[];
  /** Last 4 characters only. The full token never leaves the API. */
  token_hint: string;
  is_demo: boolean;
  last_synced_at: string | null;
  created_at: string;
}

// ───────────────────────────── core entities

export interface Service {
  id: string;
  integration_id: string;
  provider: Provider;
  external_id: string;
  name: string;
  repo: string | null;
  health_url: string | null;
  health: HealthState;
  latency_ms: number | null;
  /** Last 24 checks, oldest first. */
  health_history: { status_code: number | null; latency_ms: number | null; ok: boolean; checked_at: string }[];
  last_deploy_status: DeployStatus | null;
  last_deploy_at: string | null;
  /** Shown first on the overview. */
  pinned: boolean;
  /** Shown last on the overview, dimmed. Alerts are unaffected. Never true with `pinned`. */
  muted: boolean;
  /** Off = not polled, no incidents, hidden from the console. Only listed under its integration. */
  monitored: boolean;
}

/** Body of PUT /integrations/{id}/services: the services to keep monitoring; the rest are turned off. */
export interface MonitoredServices {
  service_ids: string[];
}

/** Body of PATCH /services/{id}. Only the fields that are sent are changed. */
export interface ServiceUpdate {
  /** A URL turns checks on, "" turns them off, null goes back to the provider's own URL. */
  health_url?: string | null;
  pinned?: boolean;
  muted?: boolean;
}

export interface Commit {
  repo: string;
  sha: string;
  message: string;
  author: string;
  committed_at: string;
  url: string | null;
}

export interface Deployment {
  id: string;
  service_id: string;
  service_name: string;
  provider: Provider;
  external_id: string;
  status: DeployStatus;
  commit_sha: string | null;
  commit_message: string | null;
  commit_author: string | null;
  branch: string | null;
  environment: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  url: string | null;
}

export interface DeploymentDetail extends Deployment {
  service: Service;
  commit: Commit | null;
  capabilities: Capability[];
  incident_id: string | null;
  /** Most recent investigation for this deployment, if any. */
  investigation_id: string | null;
}

export interface LogLine {
  /** Stable id used as an evidence reference, e.g. "log_4f2a". */
  id: string;
  ts: string;
  level: LogLevel;
  message: string;
  kind: LogKind;
}

export interface CommitDiff {
  repo: string;
  sha: string;
  message: string;
  author: string;
  files: {
    filename: string;
    status: "added" | "modified" | "removed" | "renamed";
    additions: number;
    deletions: number;
    /** Unified diff patch text; may be null for binary files. */
    patch: string | null;
  }[];
}

export interface ChangedFile {
  filename: string;
  status: "added" | "modified" | "removed" | "renamed";
  additions: number;
  deletions: number;
}

/** What separates a deployment from the last one of its service that went live. */
export interface DeploymentChanges {
  /** The last deploy that went live before this one; null when there is none on record. */
  baseline: Deployment | null;
  /** True when both deploys built the same commit: the code did not change. */
  same_commit: boolean;
  /** Other failed deploys between the baseline and this one. */
  failed_between: number;
  /** This deploy's duration minus the baseline's. */
  duration_delta_ms: number | null;
  /** Newest first. */
  commits: Commit[];
  files: ChangedFile[];
  /** "compare": exact range from the source host. "history": commits Opscend has stored. */
  source: "compare" | "history" | "none";
  truncated: boolean;
  note: string | null;
  compare_url: string | null;
}

export interface Incident {
  id: string;
  service_id: string;
  service_name: string;
  provider: Provider;
  trigger: "deploy_failed" | "health_check_failed";
  status: "open" | "resolved";
  title: string;
  deployment_id: string | null;
  investigation_id: string | null;
  opened_at: string;
  resolved_at: string | null;
}

// ───────────────────────────── timeline

export type TimelineItem =
  | { kind: "deployment"; id: string; at: string; provider: Provider; deployment: Deployment }
  | { kind: "commit"; id: string; at: string; provider: "github"; commit: Commit }
  | { kind: "incident"; id: string; at: string; provider: Provider; incident: Incident };

// ───────────────────────────── overview

export interface Overview {
  stats: {
    services: number;
    services_down: number;
    deploys_24h: number;
    failed_24h: number;
    open_incidents: number;
    investigations: number;
  };
  services: Service[];
  incidents: Incident[];
  deployments: Deployment[];
  /** Deploy counts per hour for the last 24h, oldest first. */
  activity: { hour: string; ready: number; failed: number }[];
}

// ───────────────────────────── investigator

export type EvidenceRef =
  | { type: "log"; ref: string; deployment_id: string; quote: string }
  | { type: "commit"; ref: string; quote: string }
  | { type: "deploy"; ref: string; quote: string }
  | { type: "health"; ref: string; quote: string };

export interface InvestigationReport {
  inconclusive: boolean;
  likely_cause: string;
  confidence: Confidence;
  /** Short one-line headline for lists. */
  summary: string;
  culprit_commit_sha: string | null;
  evidence: EvidenceRef[];
  suggested_fix: string | null;
  /** Filled when inconclusive: what data was missing. */
  missing: string | null;
}

export interface InvestigationStep {
  id: string;
  index: number;
  /** "llm" for a model turn, "tool" for a tool call, "report" for the final answer. */
  type: "llm" | "tool" | "report";
  /** Tool name for tool steps, model id for llm steps. */
  name: string;
  input: Record<string, unknown> | null;
  output_summary: string | null;
  started_at: string;
  duration_ms: number | null;
  tokens: number | null;
  status: "running" | "ok" | "error";
}

export interface Investigation {
  id: string;
  deployment_id: string | null;
  incident_id: string | null;
  service_name: string | null;
  status: "queued" | "running" | "completed" | "failed";
  error: string | null;
  model: string;
  tokens_used: number;
  duration_ms: number | null;
  created_at: string;
  finished_at: string | null;
  report: InvestigationReport | null;
  /** The reader's verdict on the report, if they gave one. */
  feedback: InvestigationFeedback | null;
  steps: InvestigationStep[];
}

export interface InvestigationFeedback {
  rating: "up" | "down";
  note: string | null;
  at: string;
}

/** Body of PUT /investigations/{id}/feedback. `rating: null` clears it. */
export interface InvestigationFeedbackIn {
  rating: "up" | "down" | null;
  note?: string | null;
}

export interface InvestigationStats {
  completed: number;
  inconclusive: number;
  rated: number;
  helpful: number;
  not_helpful: number;
}

// ───────────────────────────── ask opscend (chat)

export type ChatCitationType = "deploy" | "log" | "commit" | "incident" | "service";

/** A verified inline citation. The answer text carries it as `[type:ref]`. */
export interface ChatCitation {
  type: ChatCitationType;
  ref: string;
  label: string;
  /** Log citations: the cited line's text. */
  detail: string | null;
  /** The deployment page this citation links to, when there is one. */
  deployment_id: string | null;
  /** Commit citations: the commit on GitHub. */
  url: string | null;
}

/** A chart built by the chat tools from stored data. The answer places it as `[chart:<id>]`. */
export interface ChatChart {
  id: string;
  /** "bars": stacked columns per category. "line": one line per series. */
  kind: "bars" | "line";
  title: string;
  subtitle: string | null;
  /** What the y-axis counts, e.g. "deploys" or "ms". */
  unit: string;
  categories: string[];
  series: { name: string; tone: "ok" | "err" | "muted" | "info"; values: (number | null)[] }[];
}

export interface ChatStep {
  /** Tool name. */
  name: string;
  input: Record<string, unknown> | null;
  status: "running" | "ok" | "error";
  summary: string | null;
  duration_ms: number | null;
}

export interface ChatMessage {
  id: string;
  index: number;
  role: "user" | "assistant";
  /** Markdown-ish text with `[type:ref]` citation markers and `[chart:id]` lines. */
  content: string;
  /** User messages are always "done"; assistant messages start "pending". */
  status: "pending" | "running" | "done" | "failed";
  error: string | null;
  citations: ChatCitation[];
  charts: ChatChart[];
  steps: ChatStep[];
  model: string | null;
  tokens: number;
  created_at: string;
  finished_at: string | null;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatSession extends ChatSessionSummary {
  tokens_used: number;
  messages: ChatMessage[];
}

export interface ChatAskRequest {
  content: string;
}

// ───────────────────────────── developer console

export interface RawEvent {
  id: string;
  provider: Provider;
  source: "webhook" | "poll" | "demo";
  event_type: string;
  dedup_key: string;
  received_at: string;
  processed_at: string | null;
  /** True when this delivery was dropped as a duplicate of an earlier event. */
  duplicate: boolean;
  payload: unknown;
}

export interface DemoScenario {
  id: string;
  title: string;
  description: string;
}

// ───────────────────────────── notifications

export type NotificationKind = "incident_opened" | "incident_resolved" | "investigation_completed" | "investigation_failed" | "integration_error";

export interface Notification {
  id: string;
  kind: NotificationKind;
  severity: "info" | "success" | "warning" | "critical";
  title: string;
  body: string | null;
  /** Console path to open, e.g. "/console/investigations/<id>". */
  link: string | null;
  created_at: string;
  read_at: string | null;
  /** "skipped" means this event is not emailed (or SMTP is not configured). */
  email_status: "pending" | "sent" | "skipped" | "failed";
  email_error: string | null;
}

export interface NotificationList {
  unread: number;
  items: Notification[];
}

export interface NotificationSettings {
  kinds: NotificationKind[];
  email: {
    configured: boolean;
    host: string | null;
    port: number;
    security: string;
    from_address: string | null;
    to_address: string | null;
    /** Kinds that are sent by email. */
    events: NotificationKind[];
  };
}
