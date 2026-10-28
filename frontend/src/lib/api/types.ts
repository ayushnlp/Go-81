/**
 * Go 81 Sovereign AI Agent - Type Definitions
 * Aligned with Go 81 Specifications (FR1-FR4, NFR1-NFR4)
 */

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export type TaskStatus = 'queued' | 'running' | 'awaiting_approval' | 'completed' | 'failed';

export type StepStatus = 'pending' | 'running' | 'awaiting_approval' | 'completed' | 'failed';

export type MemoryType = 'episodic' | 'semantic';

export type SemanticCategory = 'fact' | 'preference' | 'entity' | 'rule';

export type SkillCategory = 'system' | 'filesystem' | 'network' | 'communication' | 'developer';

export type TriggerType = 'file_watcher' | 'cron' | 'inbox_poll' | 'system_event';

export type AudienceMode = 'user' | 'developer';

export type AppearancePreset = 'light' | 'dark' | 'oled-light' | 'oled-dark';

export interface SystemEventLog {
  id: string;
  timestamp: string;
  severity: 'INFO' | 'WARN' | 'ERROR' | 'DEBUG';
  eventType: string;
  message: string;
  taskId?: string;
  skillName?: string;
  details?: Record<string, unknown>;
}

export interface DiagnosticMetric {
  id: string;
  label: string;
  value: string | number;
  unit?: string;
  category: 'latency' | 'resource' | 'model' | 'storage';
  measured: boolean;
  note?: string;
  timestamp?: string;
}

// --- System & Agent Health ---
export interface AgentRuntimeStatus {
  online: boolean;
  model: string;
  ollamaEndpoint: string;
  ollamaStatus: 'connected' | 'disconnected' | 'degraded';
  latencyMs: number;
  cpuPercent: number;
  ramUsageMb: number;
  encryptedDatabase: {
    status: 'locked' | 'unlocked';
    algorithm: string;
    totalRecords: number;
    sizeKb: number;
  };
  telemetry: {
    outboundBytes: number;
    sovereignGuarantee: boolean;
    lastAuditTimestamp: string;
  };
  activeSentinelsCount: number;
  pendingApprovalsCount: number;
}

// --- Chat & Command Center ---
export interface ActionProposal {
  id: string;
  toolName: string;
  actionTitle: string;
  description: string;
  riskLevel: RiskLevel;
  payload: Record<string, unknown>;
  requiresApproval: boolean;
  status: 'pending' | 'approved' | 'rejected' | 'executed';
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  timestamp: string;
  thoughtTrace?: string; // Reasoning trace / chain of thought (NFR4.1)
  citedMemoryIds?: string[]; // Referenced memories from local encrypted store
  actionProposal?: ActionProposal; // Embedded approval gate
  relatedTaskId?: string;
}

// --- Autonomous Workflow & Task Execution ---
export interface TaskStep {
  id: string;
  stepNumber: number;
  title: string;
  skillName: string;
  status: StepStatus;
  parameters: Record<string, unknown>;
  output?: string;
  error?: string;
  reflectionAttempt: number; // FR3.3 self-correction loop count
  startedAt?: string;
  completedAt?: string;
  approvalRequestId?: string;
}

export interface TaskGraph {
  id: string;
  goal: string;
  status: TaskStatus;
  createdAt: string;
  updatedAt: string;
  steps: TaskStep[];
  priority: 'low' | 'normal' | 'high';
  estimatedDurationMs?: number;
  errorMessage?: string;
}

// --- Approval Gates (FR4.3 Role-Based Access Control) ---
export interface ApprovalRequest {
  id: string;
  taskId: string;
  stepId: string;
  taskGoal: string;
  actionTitle: string;
  toolName: string;
  riskLevel: RiskLevel;
  rationale: string;
  commandOrPayload: string;
  parameters: Record<string, unknown>;
  createdAt: string;
  status: 'pending' | 'approved' | 'rejected';
  resolvedAt?: string;
  resolvedBy?: string;
}

// --- Memory Vault (FR1.1, FR1.2, FR1.3, NFR4.2) ---
export interface EpisodicMemory {
  id: string;
  type: 'episodic';
  title: string;
  content: string;
  timestamp: string;
  sourceEvent: string;
  importanceScore: number; // 0.0 to 1.0
  tags: string[];
  pinned?: boolean;
}

export interface SemanticMemory {
  id: string;
  type: 'semantic';
  category: SemanticCategory;
  subject: string;
  statement: string;
  confidence: number; // 0.0 to 1.0
  updatedAt: string;
  accessCount: number;
  decayFactor: number; // 0.0 to 1.0 (forgetting mechanism FR1.3)
  embeddingDim?: number;
}

export type MemoryRecord = EpisodicMemory | SemanticMemory;

// --- Registered Skills & Dwarves' Forge (FR2) ---
export interface SkillParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default?: unknown;
}

export interface SkillDefinition {
  id: string;
  name: string;
  displayName: string;
  description: string;
  category: SkillCategory;
  isSandboxed: boolean;
  requiresApproval: boolean;
  riskLevel: RiskLevel;
  parameters: SkillParameter[];
  executionCount: number;
  lastExecutedAt?: string;
  enabled: boolean;
}

// --- Background Sentinel Triggers (FR4.1) ---
export interface SentinelTrigger {
  id: string;
  name: string;
  type: TriggerType;
  patternOrSchedule: string;
  isActive: boolean;
  lastTriggeredAt?: string;
  actionSummary: string;
  eventCount: number;
}

// --- Privacy & System Settings ---
export interface PrivacySettings {
  localOnlyMode: boolean;
  ollamaHost: string;
  selectedModel: string;
  databaseEncryption: boolean;
  memoryAutoForgetting: boolean;
  forgettingThresholdDays: number;
  maxCpuUsagePercent: number;
  rbacStrictApproval: boolean;
  backgroundTriggersEnabled: boolean;
  fastApiBackendUrl: string;
}


// --- Flight Recorder & Activity History ---
export interface FlightRecorderEvent {
  event_id: string;
  timestamp: string;
  event_type: string;
  source_type: string;
  project_id?: string;
  task_id?: string;
  step_id?: string;
  payload: Record<string, unknown>;
  evidence_hashes?: string[];
}

// --- Project Checkpoints ---
export interface ProjectCheckpoint {
  checkpoint_id: string;
  project_id: string;
  timestamp: string;
  git_commit?: string;
  state_hash: string;
  label?: string;
  description?: string;
  validation_status?: string;
  status: string;
}

// --- Audit Records ---
export interface AuditRecord {
  id: string;
  timestamp: string;
  skill_id: string;
  action: string;
  actor: string;
  parameters: Record<string, unknown>;
  status: 'allowed' | 'denied' | 'error' | 'approved' | 'rejected';
  execution_duration_ms?: number;
  violation_reason?: string;
}

// --- Filesystem & Explorer ---
export interface FileEntry {
  name: string;
  rel_path: string;
  is_dir: boolean;
  size?: number;
}

// --- Model Health Report ---
export interface ModelHealth {
  status: string;
  model: string;
  endpoint: string;
  latency_ms?: number;
  context_length?: number;
  quantization?: string;
  loaded?: boolean;
}
