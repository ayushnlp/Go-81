'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Sun, Moon } from 'lucide-react';
import { TopNav } from '@/components/shell/TopNav';
import { NavRail, NavDestination } from '@/components/shell/NavRail';
import { CentralWorkspace, ComposerMode } from '@/components/workspace/CentralWorkspace';
import { AgentCompanion } from '@/components/companion/AgentCompanion';
import { DeveloperDock } from '@/components/dock/DeveloperDock';
import { CommandPalette } from '@/components/shell/CommandPalette';
import { ApprovalModal } from '@/components/tasks/ApprovalModal';
import { ExplorerWorkspace } from '@/components/pages/ExplorerWorkspace';
import { SearchWorkspace } from '@/components/pages/SearchWorkspace';
import { GitChangesWorkspace } from '@/components/pages/GitChangesWorkspace';
import { EnvironmentWorkspace } from '@/components/pages/EnvironmentWorkspace';
import { MemoryWorkspace } from '@/components/pages/MemoryWorkspace';
import { SkillsWorkspace } from '@/components/pages/SkillsWorkspace';
import { ActivityWorkspace } from '@/components/pages/ActivityWorkspace';
import { ProblemsWorkspace } from '@/components/pages/ProblemsWorkspace';
import { SettingsWorkspace } from '@/components/pages/SettingsWorkspace';
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

const pageTitles: Record<NavDestination, string> = {
  home: 'Home',
  explorer: 'Explorer',
  search: 'Global Search',
  git: 'Git & Changes',
  activity: 'Activity History',
  problems: 'Problems & Diagnostics',
  environment: 'System Environment',
  memory: 'Memory Vault',
  skills: 'Skills Forge',
  settings: 'Settings',
};

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
  const [searchQuery, setSearchQuery] = useState('');
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
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);

  // Tasks & Approvals
  const [tasks, setTasks] = useState<TaskGraph[]>([]);
  const [activeTask, setActiveTask] = useState<TaskGraph | null>(null);
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
      const activeTheme: AppearancePreset =
        savedTheme && ['light', 'dark', 'oled-light', 'oled-dark'].includes(savedTheme)
          ? savedTheme
          : 'dark';
      setTheme(activeTheme);
      document.documentElement.setAttribute('data-theme', activeTheme);
      document.documentElement.classList.toggle('dark', activeTheme === 'dark' || activeTheme === 'oled-dark');
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
    document.documentElement.classList.toggle('dark', nextTheme === 'dark');
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

  // Handle prompt submit to backend with three-mode awareness
  const handleSubmitPrompt = async (
    overridePrompt?: string,
    overrideMode?: ComposerMode
  ) => {
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

    const effectiveMode: 'chat' | 'task' | 'memory' = overrideMode || inferIntent(promptText);

    try {
      if (effectiveMode === 'task' && isBackendOnline) {
        // Submit as autonomous task DAG to backend
        const taskRes = await api.createTask(promptText);
        if (taskRes.data) {
          setActiveTask(taskRes.data);
          setTasks((prev) => [taskRes.data!, ...prev.filter((t) => t.id !== taskRes.data!.id)]);
        }
      }

      // Send to local agent LLM chat route with explicit mode
      const agentRes = await api.sendPrompt(promptText, effectiveMode);
      setMessages((prev) => [...prev, agentRes.data]);

      // Refresh tasks and approvals if task was affected
      if (effectiveMode === 'task') {
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

  // Handle safe response regeneration (never repeats external side-effects)
  const handleRegenerateResponse = async (assistantMessageId: string) => {
    if (regeneratingId || isSending) return;

    const msgIdx = messages.findIndex((m) => m.id === assistantMessageId);
    if (msgIdx === -1) return;
    const targetMsg = messages[msgIdx];

    // Find preceding user prompt
    let precedingUserPrompt: string | null = null;
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        precedingUserPrompt = messages[i].content;
        break;
      }
    }

    if (!precedingUserPrompt) return;

    setRegeneratingId(assistantMessageId);

    try {
      // CRITICAL SAFETY REQUIREMENT:
      // Never repeat external side effects (file-writes, shell commands).
      // If the answer originated from a task execution or proposal, generate only the explanatory response
      // using mode='chat' via local Ollama.
      const isTaskOrigin = Boolean(targetMsg.relatedTaskId || targetMsg.actionProposal);
      const promptToSend = isTaskOrigin
        ? `Provide an updated explanation and summary for the completed task: ${precedingUserPrompt}`
        : precedingUserPrompt;

      const agentRes = await api.sendPrompt(promptToSend, 'chat');

      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMessageId
            ? {
                ...m,
                content: agentRes.data.content,
                thoughtTrace: agentRes.data.thoughtTrace || m.thoughtTrace,
                timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
              }
            : m
        )
      );
    } catch (err: unknown) {
      const errText = err instanceof Error ? err.message : 'Regeneration failed.';
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMessageId
            ? {
                ...m,
                content: `Regeneration failed: ${errText}`,
              }
            : m
        )
      );
    } finally {
      setRegeneratingId(null);
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
      {/* 1. Header: TopNav for Home, or Centered Page Title + Theme Toggle for non-home */}
      {activeNav === 'home' ? (
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
          onNavigate={(dest, q) => {
            if (dest === 'search') {
              setSearchQuery(q || '');
              setActiveNav('search');
            } else {
              setActiveNav(dest as NavDestination);
            }
          }}
          isCompanionOpen={isCompanionOpen}
          onToggleCompanion={() => setIsCompanionOpen((prev) => !prev)}
          isDockOpen={isDockOpen}
          onToggleDock={() => setIsDockOpen((prev) => !prev)}
        />
      ) : (
        <header className="relative h-12 w-full border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 flex items-center justify-between select-none z-30 shrink-0">
          <div className="w-8" />
          <div className="absolute inset-x-0 flex items-center justify-center pointer-events-none">
            <h1 className="text-sm font-semibold text-[var(--text-primary)] tracking-tight">
              {pageTitles[activeNav]}
            </h1>
          </div>
          <div className="flex items-center space-x-2 z-10">
            <button
              type="button"
              onClick={handleToggleTheme}
              aria-label={theme === 'dark' || theme === 'oled-dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              title={theme === 'dark' || theme === 'oled-dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              className="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors cursor-pointer flex items-center justify-center focus:outline-none"
            >
              {theme === 'dark' || theme === 'oled-dark' ? (
                <Moon className="w-4 h-4 text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors" />
              ) : (
                <Sun className="w-4 h-4 text-amber-500 hover:text-amber-600 transition-colors" />
              )}
            </button>
          </div>
        </header>
      )}

      {/* 2. Main Middle Workspace Area with Persistent NavRail */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Navigation Rail (Text-Based Navigation Menu - Persistent across all pages) */}
        <NavRail
          activeTab={activeNav}
          onSelectTab={(tab) => setActiveNav(tab)}
          pendingApprovalsCount={pendingApprovals.length}
          problemsCount={0}
        />

        {/* Dedicated Full-Page Workspaces */}
        {activeNav === 'home' && (
          <CentralWorkspace
            messages={messages}
            onRegenerate={handleRegenerateResponse}
            regeneratingId={regeneratingId}
            inputValue={inputValue}
            onInputChange={setInputValue}
            onSubmit={handleSubmitPrompt}
            isSending={isSending}
            modelHealth={modelHealth}
            activeTask={activeTask}
            mode={mode}
            onSelectActionCard={(prompt, targetMode) => {
              setInputValue(prompt);
              handleSubmitPrompt(prompt, targetMode);
            }}
            expandedTraceId={expandedTraceId}
            onToggleTrace={(id) => setExpandedTraceId((prev) => (prev === id ? null : id))}
            onOpenApprovalModal={(step) => {
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
        )}

        {activeNav === 'explorer' && <ExplorerWorkspace />}

        {activeNav === 'search' && (
          <SearchWorkspace onNavigate={(dest) => setActiveNav(dest as NavDestination)} initialQuery={searchQuery} />
        )}

        {activeNav === 'git' && (
          <GitChangesWorkspace
            onReviewChangesPrompt={() => {
              setActiveNav('home');
              handleSubmitPrompt('Review recent project modifications and summarize the current Git working tree.');
            }}
          />
        )}

        {activeNav === 'activity' && <ActivityWorkspace />}

        {activeNav === 'problems' && <ProblemsWorkspace />}

        {activeNav === 'environment' && (
          <EnvironmentWorkspace
            runtimeStatus={runtimeStatus}
            modelHealth={modelHealth}
            isBackendOnline={isBackendOnline}
            onRefresh={probeHealth}
            isLoading={isCheckingBackend}
          />
        )}

        {activeNav === 'memory' && <MemoryWorkspace />}

        {activeNav === 'skills' && <SkillsWorkspace />}

        {activeNav === 'settings' && (
          <SettingsWorkspace
            currentTheme={theme}
            onThemeChange={(t) => {
              setTheme(t);
              document.documentElement.setAttribute('data-theme', t);
              try {
                localStorage.setItem('go81_theme', t);
              } catch {
                // ignore
              }
            }}
            currentMode={mode}
            onModeChange={handleModeChange}
          />
        )}

        {/* Right-Side Agent Companion Panel (Only on Home when opened) */}
        {activeNav === 'home' && (
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
        )}
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
        }}
        mode={mode}
        onToggleMode={handleModeChange}
        theme={theme}
        onToggleTheme={handleToggleTheme}
        onNewRequest={() => {
          setActiveNav('home');
          handleNewRequest();
        }}
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
