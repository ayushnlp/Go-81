'use client';

import React, { useRef, useEffect } from 'react';
import {
  Send,
  Sparkles,
  Wrench,
  GitCommit,
  CheckCircle,
  Database,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  Loader2,
  Paperclip,
  Cpu,
  CornerDownLeft,
  Bot,
  User,
  AlertTriangle,
  PlayCircle,
  CheckCircle2,
} from 'lucide-react';
import { ChatMessage, TaskGraph, TaskStep, ModelHealth, AudienceMode } from '@/lib/api/types';

interface CentralWorkspaceProps {
  messages: ChatMessage[];
  inputValue: string;
  onInputChange: (val: string) => void;
  onSubmit: (prompt?: string) => void;
  isSending: boolean;
  modelHealth: ModelHealth | null;
  activeTask: TaskGraph | null;
  mode: AudienceMode;
  onSelectActionCard: (prompt: string) => void;
  expandedTraceId: string | null;
  onToggleTrace: (id: string) => void;
  onOpenApprovalModal?: (step: TaskStep) => void;
}

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
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isSending, activeTask]);

  // Dynamic textarea height adjustment
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [inputValue]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (inputValue.trim() && !isSending) {
        onSubmit();
      }
    }
  };

  const quickActions = [
    {
      id: 'fix-issue',
      title: 'Fix an Issue',
      description: 'Investigate errors, failed tests, or runtime exceptions.',
      icon: Wrench,
      prompt: 'Investigate the current project diagnostics, failed tests, and fix confirmed issues.',
    },
    {
      id: 'review-changes',
      title: 'Review Recent Changes',
      description: 'Inspect current file diffs and repository changes.',
      icon: GitCommit,
      prompt: 'Review recent project modifications and summarize the current Git working tree.',
    },
    {
      id: 'create-feature',
      title: 'Create Something New',
      description: 'Initiate a feature or autonomous implementation request.',
      icon: Sparkles,
      prompt: 'Propose and implement a new sovereign feature following Go 81 guidelines.',
    },
    {
      id: 'review-suggestions',
      title: 'Review Suggestions',
      description: 'Inspect proposed changes before applying them.',
      icon: CheckCircle,
      prompt: 'Review pending action proposals and audit tokens before execution.',
    },
    {
      id: 'memory-context',
      title: 'Project Notes & Memory',
      description: 'Access supported project context and saved facts.',
      icon: Database,
      prompt: 'Search memory vault for verified facts and user preferences.',
    },
  ];

  const modelDisplayName = modelHealth?.model || 'llama3.2:3b';

  return (
    <main
      aria-label="Central AI Workspace"
      className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--bg-canvas)] relative"
    >
      {/* Scrollable Workspace Container */}
      <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8 flex flex-col">
        {messages.length === 0 && !activeTask ? (
          /* =========================================================
             INITIAL / EMPTY STATE (Reference Design)
             ========================================================= */
          <div className="max-w-2xl w-full mx-auto my-auto flex flex-col items-center text-center space-y-6 pt-4 pb-8 select-none">
            {/* Header Titles */}
            <div className="space-y-2">
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[var(--text-primary)]">
                What would you like to accomplish?
              </h1>
              <p className="text-sm text-[var(--text-secondary)] max-w-md mx-auto">
                Describe what you want to build, understand, or fix.
              </p>
            </div>

            {/* Quick Actions Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full pt-2">
              {quickActions.map((action, idx) => {
                const Icon = action.icon;
                const isFullSpan = idx === quickActions.length - 1 && quickActions.length % 2 !== 0;
                return (
                  <button
                    key={action.id}
                    type="button"
                    onClick={() => onSelectActionCard(action.prompt)}
                    className={`flex items-start text-left p-3.5 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] hover:border-[var(--accent-primary-border)] transition-all group cursor-pointer shadow-2xs ${
                      isFullSpan ? 'sm:col-span-2' : ''
                    }`}
                  >
                    <div className="p-2 rounded-lg bg-[var(--bg-elevated)] group-hover:bg-[var(--accent-primary-bg)] text-[#ea580c] transition-colors mr-3 shrink-0">
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="flex-1 min-w-0 pr-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-[var(--text-primary)] group-hover:text-[var(--accent-primary)] transition-colors">
                          {action.title}
                        </span>
                        <ArrowRight className="w-3.5 h-3.5 text-[var(--text-muted)] group-hover:text-[var(--accent-primary)] group-hover:translate-x-0.5 transition-all" />
                      </div>
                      <p className="text-[11px] text-[var(--text-muted)] mt-0.5 line-clamp-2">
                        {action.description}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          /* =========================================================
             ACTIVE MESSAGES & EXECUTION VIEW
             ========================================================= */
          <div className="max-w-3xl w-full mx-auto space-y-4">
            {/* Active Task DAG Card if present */}
            {activeTask && (
              <div className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <span className="w-2 h-2 rounded-full bg-orange-500 animate-pulse" />
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
                          {step.status === 'completed' ? (
                            <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
                          ) : step.status === 'running' ? (
                            <PlayCircle className="w-4 h-4 text-orange-500 shrink-0 animate-pulse" />
                          ) : isAwaiting ? (
                            <ShieldAlert className="w-4 h-4 text-amber-500 shrink-0 animate-bounce" />
                          ) : (
                            <span className="w-4 h-4 rounded-full border border-[var(--border-subtle)] text-[10px] font-mono flex items-center justify-center shrink-0">
                              {step.stepNumber}
                            </span>
                          )}
                          <span className="truncate font-medium">
                            {step.title || step.skillName}
                          </span>
                        </div>

                        {/* Approval Trigger Button */}
                        {isAwaiting && onOpenApprovalModal && (
                          <button
                            type="button"
                            onClick={() => onOpenApprovalModal(step)}
                            className="px-2.5 py-1 rounded bg-[#ea580c] hover:bg-[#c2410c] text-white text-[11px] font-semibold transition-colors cursor-pointer shrink-0 shadow-xs"
                          >
                            Review & Authorize
                          </button>
                        )}
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

              return (
                <div
                  key={msg.id}
                  className={`flex items-start space-x-3 ${isUser ? 'justify-end' : 'justify-start'}`}
                >
                  {!isUser && (
                    <div className="w-7 h-7 rounded-lg bg-[#ea580c] flex items-center justify-center text-white shrink-0 shadow-2xs mt-1">
                      <Bot className="w-4 h-4" />
                    </div>
                  )}

                  <div
                    className={`max-w-2xl rounded-xl p-3.5 text-xs sm:text-sm leading-relaxed ${
                      isUser
                        ? 'bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-primary)]'
                        : 'bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-primary)] shadow-xs'
                    }`}
                  >
                    {/* Message Header */}
                    <div className="flex items-center justify-between text-[11px] text-[var(--text-muted)] mb-1.5 font-mono">
                      <span>{isUser ? 'You' : 'Go 81 Sovereign Agent'}</span>
                      <span>{msg.timestamp}</span>
                    </div>

                    {/* Content */}
                    <div className="whitespace-pre-wrap">{msg.content}</div>

                    {/* Thought Trace / Reasoning Accordion */}
                    {msg.thoughtTrace && (
                      <div className="mt-2.5 pt-2 border-t border-[var(--border-subtle)]">
                        <button
                          type="button"
                          onClick={() => onToggleTrace(msg.id)}
                          className="flex items-center space-x-1.5 text-[11px] font-mono text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors cursor-pointer"
                        >
                          {isExpanded ? (
                            <ChevronDown className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5" />
                          )}
                          <span>Reasoning Trace</span>
                        </button>
                        {isExpanded && (
                          <div className="mt-1.5 p-2 rounded bg-[var(--bg-canvas)] border border-[var(--border-subtle)] font-mono text-[11px] text-[var(--text-secondary)] whitespace-pre-wrap">
                            {msg.thoughtTrace}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {isUser && (
                    <div className="w-7 h-7 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] flex items-center justify-center text-[var(--text-secondary)] shrink-0 mt-1">
                      <User className="w-4 h-4" />
                    </div>
                  )}
                </div>
              );
            })}

            {isSending && (
              <div className="flex items-center space-x-3 text-xs text-[var(--text-muted)] py-2">
                <div className="w-7 h-7 rounded-lg bg-[#ea580c] flex items-center justify-center text-white shrink-0">
                  <Bot className="w-4 h-4" />
                </div>
                <div className="flex items-center space-x-2">
                  <Loader2 className="w-4 h-4 animate-spin text-[var(--accent-primary)]" />
                  <span>Generating local response via Ollama...</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* =========================================================
         BOTTOM PROMPT COMPOSER (Wide, Refined, Desktop-first)
         ========================================================= */}
      <div className="p-4 md:px-8 md:pb-6 bg-gradient-to-t from-[var(--bg-canvas)] via-[var(--bg-canvas)] to-transparent shrink-0">
        <div className="max-w-3xl w-full mx-auto">
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-md p-2.5 focus-within:border-[var(--accent-primary-border)] focus-within:ring-1 focus-within:ring-[var(--accent-primary-border)] transition-all">
            {/* Multiline Textarea */}
            <textarea
              ref={textareaRef}
              rows={2}
              value={inputValue}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message Go 81 or describe a task..."
              className="w-full bg-transparent text-xs sm:text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none resize-none leading-relaxed px-1"
            />

            {/* Composer Bottom Control Bar */}
            <div className="flex items-center justify-between pt-2 border-t border-[var(--border-subtle)] mt-1 select-none">
              <div className="flex items-center space-x-2">
                {/* Genuine Model Indicator Badge */}
                <div className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] font-mono bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                  <Cpu className="w-3 h-3 text-[#ea580c]" />
                  <span>{modelDisplayName}</span>
                </div>

                <span className="text-[10px] text-[var(--text-muted)] hidden sm:inline">
                  Shift+Enter for newline
                </span>
              </div>

              <div className="flex items-center space-x-1.5">
                {/* Submit Send Button */}
                <button
                  type="button"
                  onClick={() => onSubmit()}
                  disabled={!inputValue.trim() || isSending}
                  title="Send message (Enter)"
                  className="px-3 py-1.5 rounded-lg bg-[#ea580c] hover:bg-[#c2410c] text-white text-xs font-medium flex items-center space-x-1.5 shadow-xs transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                >
                  {isSending ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <>
                      <span>Send</span>
                      <CornerDownLeft className="w-3 h-3 opacity-80" />
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
};

