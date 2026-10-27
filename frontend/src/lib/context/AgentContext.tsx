'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import {
  AudienceMode,
  AppearancePreset,
  ChatMessage,
  TaskGraph,
  ApprovalRequest,
  MemoryRecord,
  SkillDefinition,
  SentinelTrigger,
  SystemEventLog,
  DiagnosticMetric,
  PrivacySettings,
  AgentRuntimeStatus,
} from '../api/types';
import {
  DEMO_APPROVALS,
  DEMO_CHAT_MESSAGES,
  DEMO_DIAGNOSTIC_METRICS,
  DEMO_EVENT_LOGS,
  DEMO_MEMORIES,
  DEMO_PRIVACY_SETTINGS,
  DEMO_RUNTIME_STATUS,
  DEMO_SKILLS,
  DEMO_TASKS,
  DEMO_SENTINELS,
} from '../api/fixtures';
import { api } from '../api/client';

interface AgentContextValue {
  // Mode & Appearance
  mode: AudienceMode;
  setMode: (mode: AudienceMode) => void;
  preset: AppearancePreset;
  setPreset: (preset: AppearancePreset) => void;

  // Domain State
  messages: ChatMessage[];
  tasks: TaskGraph[];
  approvals: ApprovalRequest[];
  memories: MemoryRecord[];
  skills: SkillDefinition[];
  sentinels: SentinelTrigger[];
  eventLogs: SystemEventLog[];
  diagnosticMetrics: DiagnosticMetric[];
  settings: PrivacySettings;
  runtimeStatus: AgentRuntimeStatus | null;

  // Backend Connection
  isBackendOnline: boolean;
  isCheckingBackend: boolean;
  probeBackend: () => Promise<void>;

  // Operations
  sendMessage: (prompt: string, mode?: 'chat' | 'task' | 'memory') => Promise<void>;
  createTask: (goal: string, priority?: 'low' | 'normal' | 'high') => void;
  resolveApproval: (requestId: string, decision: 'approved' | 'rejected', notes?: string) => Promise<void>;
  deleteMemory: (id: string) => Promise<void>;
  updateMemory: (id: string, newContent: string) => void;
  toggleSkill: (id: string) => void;
  toggleSentinel: (id: string) => void;
  updateSettings: (newSettings: Partial<PrivacySettings>) => Promise<void>;
}

const AgentContext = createContext<AgentContextValue | undefined>(undefined);

export const AgentProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  // 1. Audience Mode (Default 'user', persisted)
  const [mode, setModeState] = useState<AudienceMode>('user');

  // 2. Appearance Preset (Default 'dark', persisted)
  const [preset, setPresetState] = useState<AppearancePreset>('dark');

  // 3. Domain State
  const [messages, setMessages] = useState<ChatMessage[]>(DEMO_CHAT_MESSAGES);
  const [tasks, setTasks] = useState<TaskGraph[]>(DEMO_TASKS);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>(DEMO_APPROVALS);
  const [memories, setMemories] = useState<MemoryRecord[]>(DEMO_MEMORIES);
  const [skills, setSkills] = useState<SkillDefinition[]>(DEMO_SKILLS);
  const [sentinels, setSentinels] = useState<SentinelTrigger[]>(DEMO_SENTINELS);
  const [eventLogs, setEventLogs] = useState<SystemEventLog[]>(DEMO_EVENT_LOGS);
  const [diagnosticMetrics, setDiagnosticMetrics] = useState<DiagnosticMetric[]>(DEMO_DIAGNOSTIC_METRICS);
  const [settings, setSettings] = useState<PrivacySettings>(DEMO_PRIVACY_SETTINGS);
  const [runtimeStatus, setRuntimeStatus] = useState<AgentRuntimeStatus | null>(DEMO_RUNTIME_STATUS);

  // 4. Backend Connectivity
  const [isBackendOnline, setIsBackendOnline] = useState<boolean>(false);
  const [isCheckingBackend, setIsCheckingBackend] = useState<boolean>(false);

  // Initialize Mode and Theme from LocalStorage / System
  useEffect(() => {
    try {
      const savedMode = localStorage.getItem('ragnarok_mode') as AudienceMode | null;
      if (savedMode === 'user' || savedMode === 'developer') {
        setModeState(savedMode);
      }

      const savedTheme = localStorage.getItem('ragnarok_theme') as AppearancePreset | null;
      if (savedTheme && ['light', 'dark', 'oled-light', 'oled-dark'].includes(savedTheme)) {
        setPresetState(savedTheme);
        document.documentElement.setAttribute('data-theme', savedTheme);
      } else {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const initialTheme: AppearancePreset = prefersDark ? 'dark' : 'light';
        setPresetState(initialTheme);
        document.documentElement.setAttribute('data-theme', initialTheme);
      }
    } catch {
      // LocalStorage unavailable
    }
  }, []);

  const setMode = (newMode: AudienceMode) => {
    setModeState(newMode);
    try {
      localStorage.setItem('ragnarok_mode', newMode);
    } catch {
      // ignore
    }
  };

  const setPreset = (newPreset: AppearancePreset) => {
    setPresetState(newPreset);
    document.documentElement.setAttribute('data-theme', newPreset);
    try {
      localStorage.setItem('ragnarok_theme', newPreset);
    } catch {
      // ignore
    }
  };

  // Probe Backend Status
  const probeBackend = async () => {
    setIsCheckingBackend(true);
    try {
      const health = await api.checkHealth();
      setIsBackendOnline(health.online);

      if (health.online) {
        const [statRes, taskRes, memRes, skillRes, settRes] = await Promise.all([
          api.getRuntimeStatus(),
          api.getTasks(),
          api.getMemories(),
          api.getSkills(),
          api.getPrivacySettings(),
        ]);
        setRuntimeStatus(statRes.data);
        setTasks(taskRes.data);
        setMemories(memRes.data);
        setSkills(skillRes.data);
        setSettings(settRes.data);
      }
    } catch {
      setIsBackendOnline(false);
    } finally {
      setIsCheckingBackend(false);
    }
  };

  // Background probe on mount
  useEffect(() => {
    let isMounted = true;
    (async () => {
      try {
        const health = await api.checkHealth();
        if (!isMounted) return;
        setIsBackendOnline(health.online);
        if (health.online) {
          const statRes = await api.getRuntimeStatus();
          if (!isMounted) return;
          setRuntimeStatus(statRes.data);
        }
      } catch {
        // offline preview
      }
    })();
    return () => {
      isMounted = false;
    };
  }, []);

  // Operations
  const sendMessage = async (prompt: string, sendMode: 'chat' | 'task' | 'memory' = 'chat') => {
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: prompt,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);

    // Append to event logs
    const newLog: SystemEventLog = {
      id: `evt-${Date.now()}`,
      timestamp: new Date().toISOString(),
      severity: 'INFO',
      eventType: 'PROMPT_INGEST',
      message: `User submitted request in ${sendMode} mode`,
      details: { promptLength: prompt.length },
    };
    setEventLogs((prev) => [newLog, ...prev]);

    try {
      const response = await api.sendPrompt(prompt, sendMode);
      setMessages((prev) => [...prev, response.data]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: `msg-err-${Date.now()}`,
          role: 'agent',
          content: 'I could not communicate with the local agent gateway. Please verify that the local service is running.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    }
  };

  const createTask = (goal: string, priority: 'low' | 'normal' | 'high' = 'normal') => {
    const newTask: TaskGraph = {
      id: `task-${Date.now().toString().slice(-6)}`,
      goal: goal.trim(),
      status: 'running',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      priority,
      estimatedDurationMs: 25000,
      steps: [
        {
          id: `step-${Date.now()}-1`,
          stepNumber: 1,
          title: 'Understand Goal and Plan Steps',
          skillName: 'workflow.planner',
          status: 'completed',
          parameters: { goal },
          output: 'Plan generated with 3 sequential steps.',
          reflectionAttempt: 0,
        },
        {
          id: `step-${Date.now()}-2`,
          stepNumber: 2,
          title: 'Execute Local Action in Sandbox',
          skillName: 'system.sandboxed_exec',
          status: 'running',
          parameters: { isolation: 'CONTAINER_SHIELD' },
          reflectionAttempt: 0,
        },
        {
          id: `step-${Date.now()}-3`,
          stepNumber: 3,
          title: 'Store Results in Memory',
          skillName: 'memory.record_saga',
          status: 'pending',
          parameters: { autoConsolidate: true },
          reflectionAttempt: 0,
        },
      ],
    };

    setTasks((prev) => [newTask, ...prev]);

    setEventLogs((prev) => [
      {
        id: `evt-${Date.now()}`,
        timestamp: new Date().toISOString(),
        severity: 'INFO',
        eventType: 'TASK_DISPATCH',
        message: `New task graph initialized: ${goal}`,
        taskId: newTask.id,
      },
      ...prev,
    ]);
  };

  const resolveApproval = async (
    requestId: string,
    decision: 'approved' | 'rejected',
    notes?: string
  ) => {
    await api.resolveApproval(requestId, decision, notes);

    setApprovals((prev) =>
      prev.map((a) => (a.id === requestId ? { ...a, status: decision } : a))
    );

    setTasks((prev) =>
      prev.map((t) => ({
        ...t,
        status: decision === 'approved' ? 'running' : 'failed',
        steps: t.steps.map((s) => {
          if (s.approvalRequestId === requestId) {
            return {
              ...s,
              status: decision === 'approved' ? 'completed' : 'failed',
              output:
                decision === 'approved'
                  ? 'Permission granted. Step executed safely on this device.'
                  : `Permission declined: ${notes || 'Action halted by user.'}`,
            };
          }
          return s;
        }),
      }))
    );

    // Update message proposals
    setMessages((prev) =>
      prev.map((msg) => {
        if (msg.actionProposal && msg.actionProposal.id === requestId) {
          return {
            ...msg,
            actionProposal: {
              ...msg.actionProposal,
              status: decision === 'approved' ? 'approved' : 'rejected',
            },
          };
        }
        return msg;
      })
    );

    setEventLogs((prev) => [
      {
        id: `evt-${Date.now()}`,
        timestamp: new Date().toISOString(),
        severity: decision === 'approved' ? 'INFO' : 'WARN',
        eventType: 'APPROVAL_DECISION',
        message: `Approval request ${requestId} marked ${decision}`,
        details: { notes },
      },
      ...prev,
    ]);
  };

  const deleteMemory = async (id: string) => {
    await api.deleteMemory(id);
    setMemories((prev) => prev.filter((m) => m.id !== id));

    setEventLogs((prev) => [
      {
        id: `evt-${Date.now()}`,
        timestamp: new Date().toISOString(),
        severity: 'INFO',
        eventType: 'MEMORY_FORGOTTEN',
        message: `Memory item #${id} permanently deleted from local store`,
      },
      ...prev,
    ]);
  };

  const updateMemory = (id: string, newContent: string) => {
    setMemories((prev) =>
      prev.map((m) => {
        if (m.id === id) {
          if (m.type === 'semantic') {
            return { ...m, statement: newContent, updatedAt: new Date().toISOString() };
          }
          return { ...m, content: newContent };
        }
        return m;
      })
    );
  };

  const toggleSkill = (id: string) => {
    setSkills((prev) =>
      prev.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s))
    );
  };

  const toggleSentinel = (id: string) => {
    setSentinels((prev) =>
      prev.map((s) => (s.id === id ? { ...s, isActive: !s.isActive } : s))
    );
  };

  const updateSettings = async (newSettings: Partial<PrivacySettings>) => {
    await api.updatePrivacySettings(newSettings);
    setSettings((prev) => ({ ...prev, ...newSettings }));
  };

  return (
    <AgentContext.Provider
      value={{
        mode,
        setMode,
        preset,
        setPreset,
        messages,
        tasks,
        approvals,
        memories,
        skills,
        sentinels,
        eventLogs,
        diagnosticMetrics,
        settings,
        runtimeStatus,
        isBackendOnline,
        isCheckingBackend,
        probeBackend,
        sendMessage,
        createTask,
        resolveApproval,
        deleteMemory,
        updateMemory,
        toggleSkill,
        toggleSentinel,
        updateSettings,
      }}
    >
      {children}
    </AgentContext.Provider>
  );
};

export const useAgent = (): AgentContextValue => {
  const context = useContext(AgentContext);
  if (!context) {
    throw new Error('useAgent must be used within an AgentProvider');
  }
  return context;
};
