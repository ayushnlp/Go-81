'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { TopNav } from '@/components/shell/TopNav';
import { NavRail, NavDestination } from '@/components/shell/NavRail';
import { ContextualSidebar } from '@/components/sidebar/ContextualSidebar';
import { CentralWorkspace } from '@/components/workspace/CentralWorkspace';
import { AgentCompanion } from '@/components/companion/AgentCompanion';
import { DeveloperDock } from '@/components/dock/DeveloperDock';
import { CommandPalette } from '@/components/shell/CommandPalette';
import { ApprovalModal } from '@/components/tasks/ApprovalModal';
import { api } from '@/lib/api/client';
import {
  AudienceMode,
  AppearancePreset,
  ChatMessage,
  TaskGraph,
  TaskStep,
  ApprovalRequest,
  AgentRuntimeStatus,
  ModelHealth,
} from '@/lib/api/types';

/**
 * Infer intent mode based on prompt text
 */
function inferIntent(text: string): 'chat' | 'task' | 'memory' {
  const lower = text.toLowerCase().trim();
  if (
    lower.startsWith('/memory') ||
    lower.includes('search memory') ||
    lower.includes('recall memory')
  ) {
    return 'memory';
  }
  const taskKeywords = [
    'audit',
    'plan',
    'execute',
    'run ',
    'build',
    'deploy',
    'create file',
    'write file',
    'delete file',
    'compile',
    'fix',
    'refactor',
  ];
  if (taskKeywords.some((kw) => lower.includes(kw))) {
    return 'task';
  }
  return 'chat';
}

export default function CommandCenterPage() {
  // Navigation & Layout States
  const [activeNav, setActiveNav] = useState<NavDestination>('home');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isCompanionOpen, setIsCompanionOpen] = useState(false);
  const [isDockOpen, setIsDockOpen] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  // Preference States
  const [mode, setMode] = useState<AudienceMode>('user');
  const [theme, setTheme] = useState<AppearancePreset>('dark');

  // Backend Connectivity & Health
  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [isCheckingBackend, setIsCheckingBackend] = useState(false);
  const [modelHealth, setModelHealth] = useState<ModelHealth | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<AgentRuntimeStatus | null>(null);

  // Domain Workflows
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);

  // Tasks & Approvals
  const [tasks, setTasks] = useState<TaskGraph[]>([]);
  const [activeTask, setActiveTask] = useState<TaskGraph | null>(null);
  const [isLoadingTasks, setIsLoadingTasks] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequest[]>([]);
  const [activeApproval, setActiveApproval] = useState<ApprovalRequest | null>(null);

  // Probe backend and local model health
  const probeHealth = useCallback(async () => {
    setIsCheckingBackend(true);
    try {
      const [health, model, status, taskRes, appRes] = await Promise.all([
        api.checkHealth(),
        api.getModelHealth(),
        api.getRuntimeStatus(),
        api.getTasks(),
        api.getApprovals(),
      ]);

      setIsBackendOnline(health.online);
      setModelHealth(model.data);
      setRuntimeStatus(status.data);
      setTasks(taskRes.data || []);
      setPendingApprovals(appRes.data || []);
    } catch {
      setIsBackendOnline(false);
    } finally {
      setIsCheckingBackend(false);
    }
  }, []);

  // Initialize preferences and connectivity on mount
  useEffect(() => {
    try {
      const savedMode = localStorage.getItem('go81_mode') as AudienceMode | null;
      if (savedMode === 'user' || savedMode === 'developer') {
        setMode(savedMode);
      }
      const savedTheme = localStorage.getItem('go81_theme') as AppearancePreset | null;
      if (savedTheme && ['light', 'dark', 'oled-light', 'oled-dark'].includes(savedTheme)) {
        setTheme(savedTheme);
        document.documentElement.setAttribute('data-theme', savedTheme);
      } else {
        const defaultTheme: AppearancePreset = 'dark';
        setTheme(defaultTheme);
        document.documentElement.setAttribute('data-theme', defaultTheme);
      }
    } catch {
      // LocalStorage unavailable
    }

    probeHealth();
    const interval = setInterval(probeHealth, 20000);
    return () => clearInterval(interval);
  }, [probeHealth]);

  // Global keyboard shortcuts (Ctrl+K, Cmd+K)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Theme toggle handler (Instant switch, persisted in LocalStorage)
  const handleToggleTheme = () => {
    const nextTheme: AppearancePreset =
      theme === 'dark' || theme === 'oled-dark' ? 'light' : 'dark';
    setTheme(nextTheme);
    document.documentElement.setAttribute('data-theme', nextTheme);
    try {
      localStorage.setItem('go81_theme', nextTheme);
    } catch {
      // ignore
    }
  };

  // Mode change handler
  const handleModeChange = (newMode: AudienceMode) => {
    setMode(newMode);
    try {
      localStorage.setItem('go81_mode', newMode);
    } catch {
      // ignore
    }
  };

  // New Request action
  const handleNewRequest = () => {
    setMessages([]);
    setActiveTask(null);
    setInputValue('');
  };

  // Handle prompt submit to backend
  const handleSubmitPrompt = async (overridePrompt?: string) => {
    const promptText = (overridePrompt !== undefined ? overridePrompt : inputValue).trim();
    if (!promptText || isSending) return;

    setInputValue('');
    setIsSending(true);

    const userMessage: ChatMessage = {
      id: `usr-${Date.now()}`,
      role: 'user',
      content: promptText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMessage]);

    const intent = inferIntent(promptText);

    try {
      if (intent === 'task' && isBackendOnline) {
        // Submit as autonomous task DAG to backend
        const taskRes = await api.createTask(promptText);
        if (taskRes.data) {
          setActiveTask(taskRes.data);
          setTasks((prev) => [taskRes.data!, ...prev.filter((t) => t.id !== taskRes.data!.id)]);
        }
      }

      // Send to local agent LLM chat route
      const agentRes = await api.sendPrompt(promptText, intent);
      setMessages((prev) => [...prev, agentRes.data]);

      // Refresh tasks and approvals if task was affected
      if (intent === 'task') {
        const refreshedTasks = await api.getTasks();
        setTasks(refreshedTasks.data || []);
      }
    } catch (err: unknown) {
      const errorMessage: ChatMessage = {
        id: `err-${Date.now()}`,
        role: 'agent',
        content: `Execution error: ${err instanceof Error ? err.message : 'Backend connection failed.'}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsSending(false);
    }
  };

  // Resolve approval decision
  const handleResolveApproval = async (
    requestId: string,
    decision: 'approved' | 'rejected',
    notes?: string
  ) => {
    await api.resolveApproval(requestId, decision, notes);
    setPendingApprovals((prev) => prev.filter((a) => a.id !== requestId));
    probeHealth();
  };

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[var(--bg-canvas)] text-[var(--text-primary)]">
      {/* 1. Global Top Navigation Bar */}
      <TopNav
        mode={mode}
        onModeChange={handleModeChange}
        theme={theme}
        onThemeToggle={handleToggleTheme}
        isBackendOnline={isBackendOnline}
        modelHealth={modelHealth}
        runtimeStatus={runtimeStatus}
        isChecking={isCheckingBackend}
        onRefreshHealth={probeHealth}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        isCompanionOpen={isCompanionOpen}
        onToggleCompanion={() => setIsCompanionOpen((prev) => !prev)}
        isDockOpen={isDockOpen}
        onToggleDock={() => setIsDockOpen((prev) => !prev)}
      />

      {/* 2. Main Middle Workspace Area */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Navigation Rail */}
        <NavRail
          activeTab={activeNav}
          onSelectTab={(tab) => {
            setActiveNav(tab);
            if (!isSidebarOpen) setIsSidebarOpen(true);
          }}
          pendingApprovalsCount={pendingApprovals.length}
          problemsCount={0}
        />

        {/* Contextual Left Sidebar */}
        <ContextualSidebar
          activeNav={activeNav}
          isOpen={isSidebarOpen}
          onToggle={() => setIsSidebarOpen((prev) => !prev)}
          tasks={tasks}
          activeTaskId={activeTask?.id || null}
          onSelectTask={(task) => {
            setActiveTask(task);
            setActiveNav('home');
          }}
          onNewRequest={handleNewRequest}
          isLoadingTasks={isLoadingTasks}
          runtimeStatus={runtimeStatus}
          modelHealth={modelHealth}
          isBackendOnline={isBackendOnline}
          onRefreshEnvironment={probeHealth}
          onReviewChangesPrompt={() => {
            handleSubmitPrompt('Review recent project modifications and summarize the current Git working tree.');
          }}
        />

        {/* Central AI Workspace */}
        <CentralWorkspace
          messages={messages}
          inputValue={inputValue}
          onInputChange={setInputValue}
          onSubmit={handleSubmitPrompt}
          isSending={isSending}
          modelHealth={modelHealth}
          activeTask={activeTask}
          mode={mode}
          onSelectActionCard={(prompt) => {
            setInputValue(prompt);
            handleSubmitPrompt(prompt);
          }}
          expandedTraceId={expandedTraceId}
          onToggleTrace={(id) => setExpandedTraceId((prev) => (prev === id ? null : id))}
          onOpenApprovalModal={(step) => {
            // Find or synthesize approval request for step
            const req: ApprovalRequest = {
              id: step.approvalRequestId || `app-${step.id}`,
              taskId: activeTask?.id || 'active-task',
              stepId: step.id,
              taskGoal: activeTask?.goal || 'Task execution',
              actionTitle: step.title || step.skillName,
              toolName: step.skillName,
              riskLevel: 'high',
              rationale: 'Sovereign permission gateway requires user authorization to proceed.',
              commandOrPayload: JSON.stringify(step.parameters || {}),
              parameters: step.parameters || {},
              createdAt: new Date().toISOString(),
              status: 'pending',
            };
            setActiveApproval(req);
          }}
        />

        {/* Right-Side Agent Companion Panel (Split View) */}
        <AgentCompanion
          isOpen={isCompanionOpen}
          onClose={() => setIsCompanionOpen(false)}
          tasks={tasks}
          runtimeStatus={runtimeStatus}
          modelHealth={modelHealth}
          onSelectTask={(task) => {
            setActiveTask(task);
          }}
        />
      </div>

      {/* 3. Bottom Developer Dock */}
      <DeveloperDock
        isOpen={isDockOpen}
        onToggle={() => setIsDockOpen((prev) => !prev)}
        runtimeStatus={runtimeStatus}
        modelHealth={modelHealth}
        isBackendOnline={isBackendOnline}
      />

      {/* 4. Global Command Palette Modal (Ctrl+K) */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        onSelectNav={(dest) => {
          setActiveNav(dest);
          if (!isSidebarOpen) setIsSidebarOpen(true);
        }}
        mode={mode}
        onToggleMode={handleModeChange}
        theme={theme}
        onToggleTheme={handleToggleTheme}
        onNewRequest={handleNewRequest}
        onSaveCheckpoint={async () => {
          await api.createCheckpoint('Manual Checkpoint', 'Saved from command palette');
          probeHealth();
        }}
        onRunDiagnostics={probeHealth}
      />

      {/* 5. Security Approval Modal */}
      <ApprovalModal
        isOpen={activeApproval !== null}
        onClose={() => setActiveApproval(null)}
        request={activeApproval}
        onResolve={handleResolveApproval}
      />
    </div>
  );
}
