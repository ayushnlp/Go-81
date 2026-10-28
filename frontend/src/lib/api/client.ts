/**
 * Go 81 Typed API Client Boundary
 * 
 * Provides an honest transport layer to the Python FastAPI backend.
 * Features:
 * - Transparent offline fallback detection
 * - Zero direct browser-to-Ollama calls (all LLM inference routes through FastAPI)
 * - Clear labeling of staging fixtures when the backend is offline
 * - Real endpoints for chat, tasks, flight events, checkpoints, skills, system diagnostics
 */

import {
  AgentRuntimeStatus,
  ApprovalRequest,
  ChatMessage,
  MemoryRecord,
  PrivacySettings,
  SkillDefinition,
  TaskGraph,
  FlightRecorderEvent,
  ProjectCheckpoint,
  AuditRecord,
  FileEntry,
  ModelHealth,
} from './types';
import {
  DEMO_APPROVALS,
  DEMO_CHAT_MESSAGES,
  DEMO_MEMORIES,
  DEMO_PRIVACY_SETTINGS,
  DEMO_RUNTIME_STATUS,
  DEMO_SKILLS,
  DEMO_TASKS,
} from './fixtures';

export interface HealthCheckResult {
  online: boolean;
  url: string;
  latencyMs?: number;
  message?: string;
}

export interface ApiResponse<T> {
  data: T;
  isDemoFixture: boolean;
  error?: string;
}

const DEFAULT_BACKEND_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

class Go81ApiClient {
  private baseUrl: string;

  constructor() {
    this.baseUrl = DEFAULT_BACKEND_URL;
  }

  public setBaseUrl(url: string) {
    this.baseUrl = url;
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Health probe against the Python FastAPI backend
   */
  async checkHealth(): Promise<HealthCheckResult> {
    const start = performance.now();
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1500);

      const res = await fetch(`${this.baseUrl}/health`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      const latencyMs = Math.round(performance.now() - start);

      if (res.ok) {
        return { online: true, url: this.baseUrl, latencyMs };
      }
      return {
        online: false,
        url: this.baseUrl,
        latencyMs,
        message: `HTTP error ${res.status}`,
      };
    } catch (err: unknown) {
      return {
        online: false,
        url: this.baseUrl,
        message: err instanceof Error ? err.message : 'Connection refused',
      };
    }
  }

  /**
   * Health probe against Ollama via backend /api/model/health
   */
  async getModelHealth(): Promise<ApiResponse<ModelHealth>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);
      const res = await fetch(`${this.baseUrl}/api/model/health`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { data, isDemoFixture: false };
      }
    } catch {
      // Offline fallback
    }

    return {
      data: {
        status: 'disconnected',
        model: 'llama3.2:3b',
        endpoint: 'http://127.0.0.1:11434',
        loaded: false,
        latency_ms: 0,
      },
      isDemoFixture: true,
      error: 'Backend model health probe unreachable.',
    };
  }

  /**
   * Fetch live agent runtime status or demo fixture
   */
  async getRuntimeStatus(): Promise<ApiResponse<AgentRuntimeStatus>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);
      const res = await fetch(`${this.baseUrl}/api/agent/status`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { data, isDemoFixture: false };
      }
    } catch {
      // Graceful offline degradation
    }

    return {
      data: DEMO_RUNTIME_STATUS,
      isDemoFixture: true,
      error: `FastAPI backend at ${this.baseUrl} is unreachable. Displaying staging fixture.`,
    };
  }

  /**
   * Send a command or prompt to the agent
   */
  async sendPrompt(
    prompt: string,
    mode: 'chat' | 'task' | 'memory' = 'chat'
  ): Promise<ApiResponse<ChatMessage>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 60000);
      const res = await fetch(`${this.baseUrl}/api/agent/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, mode }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { data, isDemoFixture: false };
      }
    } catch {
      // Graceful offline response
    }

    // Local simulation response when offline
    const simulatedResponse: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'agent',
      content: `[Offline Staging Mode] Received: "${prompt}". Live backend at ${this.baseUrl} is unreachable. Ensure 'python -m app.main' is running.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      thoughtTrace: `Simulated pipeline: Prompt mode '${mode}' evaluated locally. Zero data transmitted externally. Connect to FastAPI backend for live local Ollama inference.`,
    };

    return {
      data: simulatedResponse,
      isDemoFixture: true,
      error: `Backend offline. Simulated locally.`,
    };
  }

  /**
   * Fetch all active & historical tasks
   */
  async getTasks(): Promise<ApiResponse<TaskGraph[]>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);
      const res = await fetch(`${this.baseUrl}/api/tasks`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const raw = await res.json();
        // Normalize TaskDAG to TaskGraph format if needed
        const normalized: TaskGraph[] = Array.isArray(raw)
          ? raw.map((t: any) => ({
              id: t.task_id || t.id,
              goal: t.goal || 'Autonomous Goal',
              status: (t.status || 'queued').toLowerCase(),
              createdAt: t.created_at || t.createdAt || new Date().toISOString(),
              updatedAt: t.updated_at || t.updatedAt || new Date().toISOString(),
              steps: (t.steps || []).map((s: any, idx: number) => ({
                id: s.step_id || s.id || `step-${idx}`,
                stepNumber: idx + 1,
                title: s.description || s.title || `Step ${idx + 1}`,
                skillName: s.skill_id || s.skillName || 'unknown',
                status: (s.status || 'pending').toLowerCase(),
                parameters: s.parameters || {},
                output: s.result ? JSON.stringify(s.result) : s.output,
                error: s.error,
                reflectionAttempt: s.retries_left !== undefined ? 3 - s.retries_left : 0,
                approvalRequestId: s.approval_token || s.approvalRequestId,
              })),
              priority: 'normal',
            }))
          : [];
        return { data: normalized, isDemoFixture: false };
      }
    } catch {
      // Graceful fallback
    }

    return {
      data: DEMO_TASKS,
      isDemoFixture: true,
      error: `Backend at ${this.baseUrl} offline. Showing staging task graphs.`,
    };
  }

  /**
   * Create and launch a new task DAG
   */
  async createTask(goal: string): Promise<ApiResponse<TaskGraph | null>> {
    try {
      const res = await fetch(`${this.baseUrl}/api/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal }),
      });
      if (res.ok) {
        const t = await res.json();
        const normalized: TaskGraph = {
          id: t.task_id || t.id,
          goal: t.goal,
          status: (t.status || 'queued').toLowerCase(),
          createdAt: t.created_at || new Date().toISOString(),
          updatedAt: t.updated_at || new Date().toISOString(),
          steps: (t.steps || []).map((s: any, idx: number) => ({
            id: s.step_id || s.id || `step-${idx}`,
            stepNumber: idx + 1,
            title: s.description || s.title || `Step ${idx + 1}`,
            skillName: s.skill_id || s.skillName || 'unknown',
            status: (s.status || 'pending').toLowerCase(),
            parameters: s.parameters || {},
            output: s.result ? JSON.stringify(s.result) : s.output,
            error: s.error,
            reflectionAttempt: 0,
            approvalRequestId: s.approval_token,
          })),
          priority: 'normal',
        };
        return { data: normalized, isDemoFixture: false };
      }
    } catch {
      // Offline fallback
    }
    return { data: null, isDemoFixture: true, error: 'Failed to create task: backend offline.' };
  }

  /**
   * Fetch pending approval requests
   */
  async getApprovals(): Promise<ApiResponse<ApprovalRequest[]>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1800);
      const res = await fetch(`${this.baseUrl}/api/approvals`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const raw = await res.json();
        const normalized = Array.isArray(raw)
          ? raw.map((a: any) => ({
              id: a.approval_id || a.id,
              taskId: a.task_id || a.taskId || '',
              stepId: a.step_id || a.stepId || '',
              taskGoal: a.task_goal || a.taskGoal || 'Approval Request',
              actionTitle: a.action_title || a.actionTitle || a.skill_id || 'Permission Gate',
              toolName: a.tool_name || a.toolName || a.skill_id || 'system',
              riskLevel: (a.risk_level || a.riskLevel || 'medium').toLowerCase(),
              rationale: a.rationale || 'Approval required by sovereign security policy.',
              commandOrPayload: a.command_or_payload || JSON.stringify(a.parameters || {}),
              parameters: a.parameters || {},
              createdAt: a.created_at || a.createdAt || new Date().toISOString(),
              status: (a.status || 'pending').toLowerCase(),
            }))
          : [];
        return { data: normalized, isDemoFixture: false };
      }
    } catch {
      // Graceful fallback
    }

    return {
      data: DEMO_APPROVALS,
      isDemoFixture: true,
    };
  }

  /**
   * Submit an approval decision (Approve or Reject)
   */
  async resolveApproval(
    requestId: string,
    decision: 'approved' | 'rejected',
    notes?: string
  ): Promise<ApiResponse<{ success: boolean; status: string }>> {
    try {
      const res = await fetch(`${this.baseUrl}/api/approvals/${requestId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, notes }),
      });
      if (res.ok) {
        const data = await res.json();
        return { data, isDemoFixture: false };
      }
    } catch {
      // Simulate locally
    }

    return {
      data: { success: true, status: decision },
      isDemoFixture: true,
    };
  }

  /**
   * Fetch memory vault records
   */
  async getMemories(type?: 'episodic' | 'semantic'): Promise<ApiResponse<MemoryRecord[]>> {
    try {
      const queryParam = type ? `?type=${type}` : '';
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);
      const res = await fetch(`${this.baseUrl}/api/memories${queryParam}`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { data, isDemoFixture: false };
      }
    } catch {
      // Graceful fallback
    }

    const filtered = type
      ? DEMO_MEMORIES.filter((m) => m.type === type)
      : DEMO_MEMORIES;

    return {
      data: filtered,
      isDemoFixture: true,
    };
  }

  /**
   * Delete a memory record
   */
  async deleteMemory(memoryId: string): Promise<ApiResponse<{ deleted: boolean }>> {
    try {
      const res = await fetch(`${this.baseUrl}/api/memories/${memoryId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        return { data: { deleted: true }, isDemoFixture: false };
      }
    } catch {
      // Simulate locally
    }

    return { data: { deleted: true }, isDemoFixture: true };
  }

  /**
   * Fetch registered skills
   */
  async getSkills(): Promise<ApiResponse<SkillDefinition[]>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);
      const res = await fetch(`${this.baseUrl}/api/skills`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const raw = await res.json();
        const normalized = Array.isArray(raw)
          ? raw.map((s: any) => ({
              id: s.id,
              name: s.name,
              displayName: s.displayName || s.name,
              description: s.description || '',
              category: (s.category || 'system').toLowerCase(),
              isSandboxed: !!s.isSandboxed,
              requiresApproval: !!s.requires_approval || !!s.requiresApproval,
              riskLevel: (s.risk_level || s.riskLevel || 'low').toLowerCase(),
              parameters: s.parameters || [],
              executionCount: s.executionCount || 0,
              enabled: s.enabled !== false,
            }))
          : [];
        return { data: normalized, isDemoFixture: false };
      }
    } catch {
      // Graceful fallback
    }

    return {
      data: DEMO_SKILLS,
      isDemoFixture: true,
    };
  }

  /**
   * Execute an enabled skill through the permission gateway and sandbox
   */
  async executeSkill(
    skillId: string,
    parameters: Record<string, unknown> = {},
    approvalToken?: string
  ): Promise<ApiResponse<any>> {
    try {
      const res = await fetch(`${this.baseUrl}/api/skills/${skillId}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parameters,
          approval_token: approvalToken,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        return { data, isDemoFixture: false };
      }
      return { data: null, isDemoFixture: false, error: data?.detail || `Execution error ${res.status}` };
    } catch (err: unknown) {
      return {
        data: null,
        isDemoFixture: true,
        error: err instanceof Error ? err.message : 'Skill execution failed',
      };
    }
  }

  /**
   * Filesystem list via built-in skill
   */
  async listFilesystem(path: string = '.', recursive: boolean = false): Promise<ApiResponse<FileEntry[]>> {
    const res = await this.executeSkill('filesystem.list', { path, recursive, max_items: 200 });
    if (res.data && res.data.result && Array.isArray(res.data.result.entries)) {
      return { data: res.data.result.entries, isDemoFixture: false };
    }
    return {
      data: [],
      isDemoFixture: res.isDemoFixture,
      error: res.error || 'Filesystem listing returned empty or unavailable.',
    };
  }

  /**
   * Fetch Flight Recorder Activity Events
   */
  async getEvents(limit: number = 50): Promise<ApiResponse<FlightRecorderEvent[]>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);
      const res = await fetch(`${this.baseUrl}/api/events?limit=${limit}`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { data: Array.isArray(data) ? data : [], isDemoFixture: false };
      }
    } catch {
      // Graceful fallback
    }
    return {
      data: [],
      isDemoFixture: true,
      error: 'Flight recorder event stream is offline.',
    };
  }

  /**
   * Fetch Project Checkpoints
   */
  async getCheckpoints(limit: number = 20): Promise<ApiResponse<ProjectCheckpoint[]>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);
      const res = await fetch(`${this.baseUrl}/api/checkpoints?limit=${limit}`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { data: Array.isArray(data) ? data : [], isDemoFixture: false };
      }
    } catch {
      // Graceful fallback
    }
    return {
      data: [],
      isDemoFixture: true,
      error: 'Project checkpoint service is offline.',
    };
  }

  /**
   * Create a Project Checkpoint
   */
  async createCheckpoint(label?: string, description?: string): Promise<ApiResponse<ProjectCheckpoint | null>> {
    try {
      const res = await fetch(`${this.baseUrl}/api/checkpoints`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: 'go-81',
          label: label || `Manual Checkpoint ${new Date().toLocaleTimeString()}`,
          description: description || 'User-initiated checkpoint from Command Center.',
        }),
      });
      if (res.ok) {
        const data = await res.json();
        return { data, isDemoFixture: false };
      }
      const err = await res.json().catch(() => null);
      return { data: null, isDemoFixture: false, error: err?.detail || 'Checkpoint creation failed' };
    } catch (e: unknown) {
      return { data: null, isDemoFixture: true, error: e instanceof Error ? e.message : 'Backend offline' };
    }
  }

  /**
   * Restore a Project Checkpoint
   */
  async restoreCheckpoint(checkpointId: string, approvalToken?: string): Promise<ApiResponse<{ restored: boolean }>> {
    try {
      const res = await fetch(`${this.baseUrl}/api/checkpoints/${checkpointId}/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approval_token: approvalToken,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        return { data: { restored: true }, isDemoFixture: false };
      }
      const err = await res.json().catch(() => null);
      return { data: { restored: false }, isDemoFixture: false, error: err?.detail || 'Checkpoint restore failed' };
    } catch (e: unknown) {
      return { data: { restored: false }, isDemoFixture: true, error: e instanceof Error ? e.message : 'Backend offline' };
    }
  }

  /**
   * Fetch audit records
   */
  async getAuditRecords(): Promise<ApiResponse<AuditRecord[]>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);
      const res = await fetch(`${this.baseUrl}/api/skills/audit/records`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { data: Array.isArray(data) ? data : [], isDemoFixture: false };
      }
    } catch {
      // Graceful fallback
    }
    return { data: [], isDemoFixture: true, error: 'Audit service offline' };
  }

  /**
   * Fetch privacy settings
   */
  async getPrivacySettings(): Promise<ApiResponse<PrivacySettings>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1800);
      const res = await fetch(`${this.baseUrl}/api/settings/privacy`, {
        signal: controller.signal,
        cache: 'no-store',
      });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { data, isDemoFixture: false };
      }
    } catch {
      // Graceful fallback
    }

    return {
      data: DEMO_PRIVACY_SETTINGS,
      isDemoFixture: true,
    };
  }

  /**
   * Update privacy settings
   */
  async updatePrivacySettings(
    settings: Partial<PrivacySettings>
  ): Promise<ApiResponse<PrivacySettings>> {
    try {
      const res = await fetch(`${this.baseUrl}/api/settings/privacy`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (res.ok) {
        const data = await res.json();
        return { data, isDemoFixture: false };
      }
    } catch {
      // Simulate locally
    }

    return {
      data: { ...DEMO_PRIVACY_SETTINGS, ...settings },
      isDemoFixture: true,
    };
  }
}

export const api = new Go81ApiClient();
export { DEMO_CHAT_MESSAGES };
