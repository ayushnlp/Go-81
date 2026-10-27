/**
 * Ragnarok Typed API Client Boundary
 * 
 * Provides an honest transport layer to the Python FastAPI backend.
 * Features:
 * - Transparent offline fallback detection
 * - Zero direct browser-to-Ollama calls (all LLM inference routes through FastAPI)
 * - Clear labeling of staging fixtures when the backend is offline
 */

import {
  AgentRuntimeStatus,
  ApprovalRequest,
  ChatMessage,
  MemoryRecord,
  PrivacySettings,
  SkillDefinition,
  TaskGraph,
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

class RagnarokApiClient {
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
   * Fetch live agent runtime status or demo fixture
   */
  async getRuntimeStatus(): Promise<ApiResponse<AgentRuntimeStatus>> {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1800);
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
      const timeoutId = setTimeout(() => controller.abort(), 8000);
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
      content: `[Offline Staging Mode] Received: "${prompt}". In live mode, this request will be processed by your local Ollama instance through the FastAPI orchestrator.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      thoughtTrace: `Simulated pipeline: Prompt mode '${mode}' evaluated. Zero data transmitted externally. Awaiting live backend connection at ${this.baseUrl}.`,
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
      const timeoutId = setTimeout(() => controller.abort(), 1800);
      const res = await fetch(`${this.baseUrl}/api/tasks`, {
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
      data: DEMO_TASKS,
      isDemoFixture: true,
      error: `Backend at ${this.baseUrl} offline. Showing staging task graphs.`,
    };
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
        const data = await res.json();
        return { data, isDemoFixture: false };
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
      const timeoutId = setTimeout(() => controller.abort(), 1800);
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
   * Delete a memory record (FR1.3 / NFR4.2 Norn's cut)
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
      const timeoutId = setTimeout(() => controller.abort(), 1800);
      const res = await fetch(`${this.baseUrl}/api/skills`, {
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
      data: DEMO_SKILLS,
      isDemoFixture: true,
    };
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

export const api = new RagnarokApiClient();
export { DEMO_CHAT_MESSAGES };
