'use client';

import React, { useRef, useEffect, useState } from 'react';
import {
  ArrowUp,
  Loader2,
  Bot,
  User,
  MoreHorizontal,
  ThumbsUp,
  ThumbsDown,
  Copy,
  Check,
  Clock,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { ChatMessage, TaskGraph, TaskStep, ModelHealth, AudienceMode } from '@/lib/api/types';

export type ComposerMode = 'chat' | 'task' | 'memory';

interface CentralWorkspaceProps {
  messages: ChatMessage[];
  inputValue: string;
  onInputChange: (val: string) => void;
  onSubmit: (prompt?: string, mode?: ComposerMode) => void;
  isSending: boolean;
  modelHealth: ModelHealth | null;
  activeTask: TaskGraph | null;
  mode: AudienceMode;
  onSelectActionCard: (prompt: string, mode?: ComposerMode) => void;
  expandedTraceId: string | null;
  onToggleTrace: (id: string) => void;
  onOpenApprovalModal?: (step: TaskStep) => void;
  onRegenerate?: (messageId: string) => void;
  regeneratingId?: string | null;
}

function formatMessageDetails(timestampStr: string) {
  const now = new Date();
  const dateStr = now.toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  const timeStr = timestampStr || now.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
  const tzName = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Local';
  const tzOffset = -now.getTimezoneOffset();
  const sign = tzOffset >= 0 ? '+' : '-';
  const hours = String(Math.floor(Math.abs(tzOffset) / 60)).padStart(2, '0');
  const mins = String(Math.abs(tzOffset) % 60).padStart(2, '0');
  const timezoneStr = `UTC${sign}${hours}:${mins} (${tzName})`;

  return { dateStr, timeStr, timezoneStr };
}

interface SmartSuggestion {
  id: string;
  title: string;
  prompt: string;
  targetMode: ComposerMode;
  keywords: string[];
}

const smartSuggestionsPool: SmartSuggestion[] = [
  {
    id: 'fix-issue',
    title: 'Fix an issue — Investigate diagnostics and fix failing tests',
    prompt: 'Investigate the current project diagnostics, failed tests, and fix confirmed issues.',
    targetMode: 'task',
    keywords: ['test', 'fail', 'error', 'bug', 'issue', 'broken', 'fix', 'problem', 'exception'],
  },
  {
    id: 'inspect-tests',
    title: 'Inspect failing tests — Run test suite and review failure trace',
    prompt: 'Run the project test suite, isolate failing test cases, and summarize root causes.',
    targetMode: 'task',
    keywords: ['test', 'failing', 'suite', 'unit', 'pytest', 'jest', 'assert'],
  },
  {
    id: 'review-changes',
    title: 'Review recent changes — Inspect current working tree git diff',
    prompt: 'Review recent project modifications and summarize the current Git working tree.',
    targetMode: 'task',
    keywords: ['git', 'change', 'diff', 'commit', 'branch', 'working', 'status', 'uncommitted'],
  },
  {
    id: 'plan-feature',
    title: 'Plan a new feature — Propose architecture and execution DAG',
    prompt: 'Propose and implement a new sovereign feature following Go 81 guidelines.',
    targetMode: 'task',
    keywords: ['build', 'create', 'feature', 'new', 'implement', 'add', 'architecture', 'develop'],
  },
  {
    id: 'review-architecture',
    title: 'Review existing architecture — Check project structure and schemas',
    prompt: 'Analyze current project architecture, dependencies, and state boundaries.',
    targetMode: 'task',
    keywords: ['architecture', 'structure', 'schema', 'design', 'system', 'component'],
  },
  {
    id: 'prepare-workflow',
    title: 'Prepare an implementation workflow — Generate structured steps',
    prompt: 'Generate a structured execution DAG with verification steps for my goal.',
    targetMode: 'task',
    keywords: ['workflow', 'dag', 'steps', 'orchestrate', 'plan', 'task', 'goal'],
  },
  {
    id: 'search-decisions',
    title: 'Search project decisions — Retrieve verified facts and preferences',
    prompt: 'Search memory vault for verified facts and user preferences.',
    targetMode: 'memory',
    keywords: ['memory', 'preference', 'fact', 'remember', 'decision', 'recall', 'vault', 'saved', 'note'],
  },
  {
    id: 'retrieve-facts',
    title: 'Retrieve related semantic facts — Query local knowledge base',
    prompt: 'Retrieve verified semantic memories related to current project architecture.',
    targetMode: 'memory',
    keywords: ['semantic', 'fact', 'knowledge', 'retrieve', 'stored', 'memory'],
  },
  {
    id: 'explain-dag',
    title: 'Explain execution DAG — How Go 81 orchestrates autonomous tasks',
    prompt: 'Explain how Go 81 plans, validates, and executes autonomous task DAGs.',
    targetMode: 'chat',
    keywords: ['explain', 'how', 'what', 'why', 'help', 'question', 'tell', 'learn'],
  },
];

export const CentralWorkspace: React.FC<CentralWorkspaceProps> = ({
  messages,
  inputValue,
  onInputChange,
  onSubmit,
  isSending,
  modelHealth,
  activeTask,
  mode,
  onSelectActionCard,
  expandedTraceId,
  onToggleTrace,
  onOpenApprovalModal,
  onRegenerate,
  regeneratingId,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [feedbackState, setFeedbackState] = useState<Record<string, 'like' | 'dislike'>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [activeDetailsId, setActiveDetailsId] = useState<string | null>(null);
  const [openUserMenuId, setOpenUserMenuId] = useState<string | null>(null);
  const [composerMode, setComposerMode] = useState<ComposerMode>('chat');

  const hasActiveContent = messages.length > 0 || !!activeTask;

  // Auto-scroll to bottom of messages
  useEffect(() => {
    if (hasActiveContent) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isSending, activeTask, hasActiveContent]);

  // Dynamic textarea height adjustment
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 140)}px`;
    }
  }, [inputValue]);

  // Global dismiss for popovers and menus on outside click or Escape
  useEffect(() => {
    const handleGlobalClick = () => {
      setOpenUserMenuId(null);
      setActiveDetailsId(null);
    };
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpenUserMenuId(null);
        setActiveDetailsId(null);
      }
    };
    window.addEventListener('click', handleGlobalClick);
    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => {
      window.removeEventListener('click', handleGlobalClick);
      window.removeEventListener('keydown', handleGlobalKeyDown);
    };
  }, []);

  const handleCopy = (id: string, text: string) => {
    try {
      if (navigator?.clipboard?.writeText) {
        navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setCopiedId(id);
      setTimeout(() => setCopiedId((prev) => (prev === id ? null : prev)), 2000);
    } catch {
      // ignore
    }
  };

  const handleToggleFeedback = (id: string, type: 'like' | 'dislike') => {
    setFeedbackState((prev) => {
      const current = prev[id];
      if (current === type) {
        const next = { ...prev };
        delete next[id];
        return next;
      }
      return { ...prev, [id]: type };
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (inputValue.trim() && !isSending) {
        onSubmit(inputValue, composerMode);
      }
    }
  };

  // Contextual smart suggestions: only shown when user enters >= 2 chars
  const getContextualSuggestions = (): SmartSuggestion[] => {
    const raw = inputValue.trim().toLowerCase();
    if (raw.length < 2) return [];

    const tokens = raw.split(/\s+/).filter(Boolean);

    const scored = smartSuggestionsPool
      .map((item) => {
        let score = 0;
        if (item.targetMode === composerMode) score += 2;
        for (const kw of item.keywords) {
          if (tokens.some((tok) => tok.includes(kw) || kw.includes(tok))) {
            score += 5;
          }
        }
        return { item, score };
      })
      .filter((s) => s.score > 1)
      .sort((a, b) => b.score - a.score);

    return scored.slice(0, 3).map((s) => s.item);
  };

  const contextualSuggestions = getContextualSuggestions();

  // Mode selection options definition
  const modeOptions: { id: ComposerMode; label: string }[] = [
    { id: 'chat', label: 'Chat & Query' },
    { id: 'task', label: 'Autonomous Workflow' },
    { id: 'memory', label: 'Semantic Memory' },
  ];

  // ChatGPT-style segmented mode selector capsule (placed OUTSIDE the composer)
  const renderModeSelector = () => (
    <div className="inline-flex items-center p-1 rounded-full bg-[var(--bg-elevated)] border border-[var(--border-subtle)] shadow-xs select-none">
      {modeOptions.map((opt) => {
        const isActive = composerMode === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            onClick={() => setComposerMode(opt.id)}
            className={`px-4 py-1.5 rounded-full text-xs sm:text-[13px] transition-all cursor-pointer focus:outline-none ${
              isActive
                ? 'bg-[var(--bg-surface)] text-[#F4511E] dark:text-[#ea580c] font-semibold shadow-xs'
                : 'text-[#18181B] dark:text-[#A1A1AA] hover:text-[#F4511E] dark:hover:text-[#F4F4F5] font-medium'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );

  // Slim, pill-shaped composer (clean, single rounded container, no internal tabs)
  const renderComposer = (isCenteredEmpty: boolean = false) => {
    const placeholder =
      composerMode === 'chat'
        ? 'Ask anything or query Go 81...'
        : composerMode === 'task'
        ? 'Describe the outcome you want Go 81 to accomplish...'
        : 'Search your saved memories and verified facts...';

    return (
      <div className={`w-full max-w-[780px] mx-auto ${isCenteredEmpty ? 'my-2' : ''}`}>
        <div className="min-h-[56px] rounded-full border border-[var(--border-subtle)] bg-[var(--bg-composer)] pl-5 pr-2 py-1.5 flex items-center justify-between focus-within:border-[var(--accent-primary-border)] focus-within:ring-1 focus-within:ring-[var(--accent-primary-border)] transition-all shadow-xs">
          <textarea
            ref={textareaRef}
            rows={1}
            value={inputValue}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="flex-1 bg-transparent text-sm sm:text-[15px] text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none focus:outline-none focus-visible:outline-none focus:ring-0 focus-visible:ring-0 resize-none leading-normal px-1 border-0 ring-0 shadow-none"
          />
          <button
            type="button"
            onClick={() => {
              if (inputValue.trim() && !isSending) {
                onSubmit(inputValue, composerMode);
              }
            }}
            disabled={!inputValue.trim() || isSending}
            aria-label="Send message"
            title="Send message (Enter)"
            className="w-10 h-10 rounded-full bg-[#F4511E] hover:bg-[#c2410c] text-white flex items-center justify-center shrink-0 ml-2 transition-all disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer shadow-xs active:scale-95"
          >
            {isSending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ArrowUp className="w-5 h-5 stroke-[2.5]" />
            )}
          </button>
        </div>
      </div>
    );
  };

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--bg-canvas)] relative">
      {/* Scrollable Center Canvas */}
      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 space-y-6">
        {!hasActiveContent ? (
          /* =========================================================
             A. EMPTY STATE: 
             1. Three-Mode Selector
             2. Centered Welcome Heading
             3. Small Subtitle
             4. Single Rounded Composer
             5. Text Suggestions (Only while typing >= 2 chars)
             ========================================================= */
          <div className="max-w-2xl mx-auto flex flex-col items-center justify-center min-h-[75vh] space-y-6 text-center select-none">
            {/* 1. Horizontal Pill-Shaped Segmented Mode Selector */}
            <div>
              {renderModeSelector()}
            </div>

            {/* 2 & 3. Header Text & Dynamic Subtitle */}
            <div className="space-y-1.5">
              <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-[var(--text-primary)]">
                What would you like to do?
              </h2>
              <p className="text-xs sm:text-sm text-[var(--text-muted)]">
                {composerMode === 'chat'
                  ? 'Your personal autonomous AI workspace.'
                  : composerMode === 'task'
                  ? 'Plan, execute, and verify complex tasks locally.'
                  : 'Retrieve relevant knowledge from your local semantic memory.'}
              </p>
            </div>

            {/* 4. Centered Composer for Fresh Conversation */}
            <div className="w-full">
              {renderComposer(true)}
            </div>

            {/* 5. Smart Contextual Suggestions (Shown ONLY when user begins typing >= 2 chars) */}
            {contextualSuggestions.length > 0 && (
              <div className="flex flex-col items-center space-y-1.5 pt-1 w-full max-w-[640px]">
                {contextualSuggestions.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      onInputChange(s.prompt);
                      if (s.targetMode && s.targetMode !== composerMode) {
                        setComposerMode(s.targetMode);
                      }
                    }}
                    className="text-xs sm:text-[13px] text-[var(--text-secondary)] hover:text-[#F4511E] dark:hover:text-[#ea580c] transition-colors cursor-pointer text-center w-full truncate py-0.5 focus:outline-none"
                  >
                    {s.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          /* =========================================================
             B. ACTIVE CONVERSATION STATE
             Messages history, execution DAG, and bottom composer
             ========================================================= */
          <div className="max-w-3xl w-full mx-auto space-y-4 pb-4">
            {/* Active Task DAG Card if present */}
            {activeTask && (
              <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="w-2 h-2 rounded-full bg-[#F4511E] animate-pulse" />
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      Autonomous DAG Execution
                    </span>
                  </div>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                    {activeTask.status.toUpperCase()}
                  </span>
                </div>
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  {activeTask.goal}
                </h3>

                {/* Steps List */}
                <div className="space-y-1.5 pt-1">
                  {activeTask.steps.map((step) => {
                    const isAwaiting = step.status === 'awaiting_approval';
                    return (
                      <div
                        key={step.id}
                        className={`p-2.5 rounded-lg border text-xs flex items-center justify-between transition-colors ${
                          isAwaiting
                            ? 'bg-amber-500/10 border-amber-500/30 text-amber-500'
                            : step.status === 'completed'
                            ? 'bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)]'
                            : step.status === 'running'
                            ? 'bg-orange-500/10 border-orange-500/20 text-orange-500'
                            : 'bg-[var(--bg-surface)] border-[var(--border-subtle)] text-[var(--text-muted)]'
                        }`}
                      >
                        <div className="flex items-center space-x-2.5 truncate pr-2">
                          <span className="font-mono text-[11px] text-[var(--text-muted)]">
                            {step.id}
                          </span>
                          <span className="font-medium text-[var(--text-primary)] truncate">
                            {step.title}
                          </span>
                        </div>

                        <div className="flex items-center space-x-2 shrink-0">
                          {isAwaiting && onOpenApprovalModal && (
                            <button
                              type="button"
                              onClick={() => onOpenApprovalModal(step)}
                              className="px-2 py-0.5 rounded bg-amber-500 hover:bg-amber-600 text-white font-semibold text-[10px] uppercase tracking-wider transition-colors cursor-pointer"
                            >
                              Review
                            </button>
                          )}
                          <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                            {step.status}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Conversation Messages */}
            {messages.map((msg) => {
              const isUser = msg.role === 'user';
              const isExpanded = expandedTraceId === msg.id;
              const isMenuOpen = openUserMenuId === msg.id;
              const isDetailsOpen = activeDetailsId === msg.id;
              const isCopied = copiedId === msg.id;
              const feedback = feedbackState[msg.id];
              const isRegenerating = regeneratingId === msg.id;
              const details = formatMessageDetails(msg.timestamp);

              if (isUser) {
                return (
                  <div
                    key={msg.id}
                    className="w-full flex items-center justify-end group relative mb-4"
                  >
                    {/* Three-dot action button */}
                    <div className="relative mr-2 flex items-center">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenUserMenuId(isMenuOpen ? null : msg.id);
                          setActiveDetailsId(null);
                        }}
                        aria-label="User message options"
                        title="More options"
                        className="opacity-0 group-hover:opacity-100 focus:opacity-100 p-1.5 rounded-md hover:bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all cursor-pointer focus:outline-none"
                      >
                        <MoreHorizontal className="w-4 h-4" />
                      </button>

                      {isMenuOpen && (
                        <div
                          onClick={(e) => e.stopPropagation()}
                          className="absolute right-0 bottom-full mb-1.5 z-50 w-44 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-1 shadow-lg text-xs"
                        >
                          <button
                            type="button"
                            onClick={() => {
                              handleCopy(msg.id, msg.content);
                              setOpenUserMenuId(null);
                            }}
                            className="w-full flex items-center space-x-2 px-2.5 py-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-left transition-colors cursor-pointer text-[var(--text-primary)]"
                          >
                            {isCopied ? (
                              <Check className="w-3.5 h-3.5 text-emerald-500" />
                            ) : (
                              <Copy className="w-3.5 h-3.5 text-[var(--text-muted)]" />
                            )}
                            <span>{isCopied ? 'Copied' : 'Copy Message'}</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => {
                              setActiveDetailsId(isDetailsOpen ? null : msg.id);
                              setOpenUserMenuId(null);
                            }}
                            className="w-full flex items-center space-x-2 px-2.5 py-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-left transition-colors cursor-pointer text-[var(--text-primary)]"
                          >
                            <Clock className="w-3.5 h-3.5 text-[var(--text-muted)]" />
                            <span>Message Details</span>
                          </button>
                        </div>
                      )}

                      {isDetailsOpen && (
                        <div
                          onClick={(e) => e.stopPropagation()}
                          className="absolute right-0 bottom-full mb-1.5 z-50 w-64 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-3 shadow-xl text-xs space-y-1.5"
                        >
                          <div className="flex items-center justify-between text-[11px] font-semibold text-[var(--text-muted)] border-b border-[var(--border-subtle)] pb-1">
                            <span>MESSAGE DETAILS</span>
                            <button
                              type="button"
                              onClick={() => setActiveDetailsId(null)}
                              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
                            >
                              ✕
                            </button>
                          </div>
                          <div className="space-y-1 text-[11px] text-[var(--text-secondary)]">
                            <div><span className="font-medium text-[var(--text-primary)]">Date:</span> {details.dateStr}</div>
                            <div><span className="font-medium text-[var(--text-primary)]">Time:</span> {details.timeStr}</div>
                            <div><span className="font-medium text-[var(--text-primary)]">Timezone:</span> {details.timezoneStr}</div>
                            <div className="pt-1 text-[10px] text-[var(--text-muted)] font-mono">ID: {msg.id}</div>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Compact Rounded Bubble */}
                    <div className="max-w-[80%] sm:max-w-[70%] px-4 py-2.5 rounded-2xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-sm leading-relaxed shadow-2xs select-text">
                      <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                    </div>
                  </div>
                );
              }

              return (
                <div key={msg.id} className="w-full flex flex-col space-y-2 mb-6 group select-text">
                  {/* Thought trace if available */}
                  {msg.thoughtTrace && (
                    <div className="mb-2">
                      <button
                        type="button"
                        onClick={() => onToggleTrace(msg.id)}
                        className="flex items-center space-x-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors cursor-pointer py-1"
                      >
                        <Sparkles className="w-3.5 h-3.5 text-[#F4511E]" />
                        <span>{isExpanded ? 'Hide Thought Process' : 'View Thought Process'}</span>
                      </button>
                      {isExpanded && (
                        <div className="mt-2 p-3 rounded-xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-xs text-[var(--text-secondary)] font-mono whitespace-pre-wrap leading-relaxed">
                          {msg.thoughtTrace}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Direct Assistant Text */}
                  <div className="text-sm sm:text-[15px] leading-relaxed text-[var(--text-primary)] whitespace-pre-wrap break-words">
                    {msg.content}
                  </div>

                  {/* Assistant Message Actions Toolbar */}
                  <div className="flex items-center space-x-2 pt-2 text-[var(--text-muted)] text-xs">
                    <span className="text-[11px] font-mono mr-2">{msg.timestamp}</span>

                    <button
                      type="button"
                      onClick={() => handleCopy(msg.id, msg.content)}
                      aria-label="Copy response"
                      title="Copy response"
                      className="p-1 rounded hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] transition-colors cursor-pointer focus:outline-none"
                    >
                      {isCopied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>

                    <button
                      type="button"
                      onClick={() => handleToggleFeedback(msg.id, 'like')}
                      aria-label="Good response"
                      title="Good response"
                      className={`p-1 rounded hover:bg-[var(--bg-elevated)] transition-colors cursor-pointer focus:outline-none ${
                        feedback === 'like' ? 'text-emerald-500' : 'hover:text-[var(--text-primary)]'
                      }`}
                    >
                      <ThumbsUp className="w-3.5 h-3.5" />
                    </button>

                    <button
                      type="button"
                      onClick={() => handleToggleFeedback(msg.id, 'dislike')}
                      aria-label="Bad response"
                      title="Bad response"
                      className={`p-1 rounded hover:bg-[var(--bg-elevated)] transition-colors cursor-pointer focus:outline-none ${
                        feedback === 'dislike' ? 'text-rose-500' : 'hover:text-[var(--text-primary)]'
                      }`}
                    >
                      <ThumbsDown className="w-3.5 h-3.5" />
                    </button>

                    {onRegenerate && (
                      <button
                        type="button"
                        onClick={() => onRegenerate(msg.id)}
                        disabled={isRegenerating || isSending}
                        aria-label="Regenerate explanation"
                        title="Regenerate explanation (Safe)"
                        className="p-1 rounded hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)] transition-colors cursor-pointer disabled:opacity-40 focus:outline-none"
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${isRegenerating ? 'animate-spin text-[#F4511E]' : ''}`} />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}

            {isSending && (
              <div className="flex items-center space-x-3 text-xs text-[var(--text-muted)] py-2">
                <div className="w-7 h-7 rounded-lg bg-[#F4511E] flex items-center justify-center text-white shrink-0">
                  <Bot className="w-4 h-4" />
                </div>
                <div className="flex items-center space-x-2">
                  <Loader2 className="w-4 h-4 animate-spin text-[#F4511E]" />
                  <span>Generating local response via Ollama...</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Sticky Bottom Composer: Only in Active Conversation State */}
      {hasActiveContent && (
        <div className="p-4 md:px-8 md:pb-6 bg-gradient-to-t from-[var(--bg-canvas)] via-[var(--bg-canvas)] to-transparent shrink-0 flex flex-col items-center space-y-2">
          {/* Segmented Mode Selector Capsule */}
          {renderModeSelector()}

          {/* Slim Pill-Shaped Composer */}
          {renderComposer(false)}

          {/* Contextual Suggestions while typing in active conversation */}
          {contextualSuggestions.length > 0 && (
            <div className="flex flex-col items-center space-y-1 pt-1 w-full max-w-[640px]">
              {contextualSuggestions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => {
                    onInputChange(s.prompt);
                    if (s.targetMode && s.targetMode !== composerMode) {
                      setComposerMode(s.targetMode);
                    }
                  }}
                  className="text-xs sm:text-[13px] text-[var(--text-secondary)] hover:text-[#F4511E] dark:hover:text-[#ea580c] transition-colors cursor-pointer text-center w-full truncate py-0.5 focus:outline-none"
                >
                  {s.title}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </main>
  );
};
