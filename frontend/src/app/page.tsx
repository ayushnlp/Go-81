'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  ShieldAlert,
  Check,
  Sparkles,
  Plus,
  Paperclip,
  Keyboard,
  Trash2,
  RefreshCw,
  MoreHorizontal,
} from 'lucide-react';
import { AppSidebar } from '@/components/shell/AppSidebar';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ApprovalModal } from '@/components/tasks/ApprovalModal';
import { api } from '@/lib/api/client';
import {
  ChatMessage,
  ApprovalRequest,
  AgentRuntimeStatus,
} from '@/lib/api/types';
import { DEMO_APPROVALS } from '@/lib/api/fixtures';

/**
 * Route request according to user instruction and supported intent-handling logic
 */
function inferIntentMode(text: string): 'chat' | 'task' | 'memory' {
  const lower = text.toLowerCase().trim();
  if (
    lower.startsWith('/memory') ||
    lower.startsWith('search memory') ||
    lower.startsWith('recall memory') ||
    lower.includes('search memory') ||
    lower.includes('search memories')
  ) {
    return 'memory';
  }
  const taskKeywords = [
    'audit',
    'plan',
    'execute',
    'run ',
    'create file',
    'write file',
    'delete file',
    'rm ',
    'build',
    'deploy',
    'kill',
    'compile',
    'clone',
    'git commit',
    'push',
    'format disk',
    'modify file',
    'update file',
  ];
  if (taskKeywords.some((kw) => lower.includes(kw))) {
    return 'task';
  }
  return 'chat';
}

export default function CommandCenterPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [activeMode, setActiveMode] = useState<'chat' | 'task' | 'memory'>('chat');
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);

  // Plus menu & shortcuts modal states
  const [isPlusMenuOpen, setIsPlusMenuOpen] = useState(false);
  const [showShortcutsModal, setShowShortcutsModal] = useState(false);
  const plusMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // System & Backend connection states
  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [isCheckingBackend, setIsCheckingBackend] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<AgentRuntimeStatus | null>(null);

  // Approval Gate state
  const [activeApproval, setActiveApproval] = useState<ApprovalRequest | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Adjust textarea height dynamically to content
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`;
    }
  }, [inputValue]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (plusMenuRef.current && !plusMenuRef.current.contains(e.target as Node)) {
        setIsPlusMenuOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsPlusMenuOpen(false);
        setShowShortcutsModal(false);
      }
    };
    if (isPlusMenuOpen || showShortcutsModal) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isPlusMenuOpen, showShortcutsModal]);

  const probeBackend = async () => {
    setIsCheckingBackend(true);
    try {
      const health = await api.checkHealth();
      setIsBackendOnline(health.online);
      const statusRes = await api.getRuntimeStatus();
      setRuntimeStatus(statusRes.data);
    } finally {
      setIsCheckingBackend(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    (async () => {
      try {
        const health = await api.checkHealth();
        if (!isMounted) return;
        setIsBackendOnline(health.online);
        const statusRes = await api.getRuntimeStatus();
        if (!isMounted) return;
        setRuntimeStatus(statusRes.data);
      } catch {
        // graceful offline
      }
    })();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result;
      if (typeof text === 'string') {
        const snippet = text.slice(0, 4000);
        setInputValue((prev) =>
          prev
            ? `${prev}\n\n[Attached: ${file.name}]\n${snippet}`
            : `[Attached: ${file.name}]\n${snippet}`
        );
      }
    };
    reader.readAsText(file);
    e.target.value = '';
    setIsPlusMenuOpen(false);
  };

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputValue.trim() || isSending) return;

    const userText = inputValue.trim();
    setInputValue('');

    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: userText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsSending(true);

    // Retain focus on composer
    setTimeout(() => {
      textareaRef.current?.focus();
    }, 0);

    try {
      const modeToSend = activeMode !== 'chat' ? activeMode : inferIntentMode(userText);
      const response = await api.sendPrompt(userText, modeToSend);
      setMessages((prev) => [...prev, response.data]);
    } catch {
      // Local fallback in case of network trap
      setMessages((prev) => [
        ...prev,
        {
          id: `msg-err-${Date.now()}`,
          role: 'agent',
          content: 'Unable to communicate with the local agent gateway. Check Ollama daemon.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const handleResolveApproval = async (
    requestId: string,
    decision: 'approved' | 'rejected',
    notes?: string
  ) => {
    await api.resolveApproval(requestId, decision, notes);
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
  };

  /**
   * Mode Selector Tabs: Chat | Autonomous Workflow | Semantic Memory Search
   */
  const renderModeTabs = () => (
    <div className="flex items-center justify-center gap-6 mb-3 text-xs sm:text-[13px] font-medium">
      <button
        type="button"
        onClick={() => setActiveMode('chat')}
        className={`cursor-pointer transition-colors pb-1 ${
          activeMode === 'chat'
            ? 'text-[#14213D] font-semibold border-b-2 border-[#14213D]'
            : 'text-[#667085] hover:text-[#14213D] border-b-2 border-transparent'
        }`}
      >
        Chat
      </button>
      <button
        type="button"
        onClick={() => setActiveMode('task')}
        className={`cursor-pointer transition-colors pb-1 ${
          activeMode === 'task'
            ? 'text-[#14213D] font-semibold border-b-2 border-[#14213D]'
            : 'text-[#667085] hover:text-[#14213D] border-b-2 border-transparent'
        }`}
      >
        Autonomous Workflow
      </button>
      <button
        type="button"
        onClick={() => setActiveMode('memory')}
        className={`cursor-pointer transition-colors pb-1 ${
          activeMode === 'memory'
            ? 'text-[#14213D] font-semibold border-b-2 border-[#14213D]'
            : 'text-[#667085] hover:text-[#14213D] border-b-2 border-transparent'
        }`}
      >
        Semantic Memory Search
      </button>
    </div>
  );

  /**
   * Minimal, Fully Rounded ChatGPT-Inspired Composer Component
   */
  const renderComposer = () => (
    <div className="relative w-full max-w-[760px] mx-auto">
      {/* Hidden File Input for authentic attachment */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
        accept=".txt,.md,.json,.py,.ts,.tsx,.js,.jsx,.csv,.log,.sh"
      />

      <div className="rounded-[28px] border border-[#E2E8F0] bg-[#F4F4F6] hover:bg-[#EFEFF2] focus-within:bg-white focus-within:border-[#CBD5E1] focus-within:ring-2 focus-within:ring-[#14213D]/5 transition-all px-2.5 py-1.5 sm:px-3 sm:py-2 flex items-end gap-2 shadow-xs">
        {/* Plus Icon on Left */}
        <div className="relative shrink-0" ref={plusMenuRef}>
          <button
            type="button"
            onClick={() => setIsPlusMenuOpen((prev) => !prev)}
            aria-label="Add attachment or action"
            title="Attach file or action"
            className="flex h-8 w-8 sm:h-9 sm:w-9 items-center justify-center rounded-full text-[#667085] hover:bg-[#E4E7EC] hover:text-[#14213D] transition-colors cursor-pointer"
          >
            <Plus className="w-5 h-5" />
          </button>

          {/* Plus Menu Popup */}
          {isPlusMenuOpen && (
            <div className="absolute left-0 bottom-full mb-2 w-48 rounded-xl border border-[#E4E9F1] bg-white p-1 shadow-lg z-30 text-xs text-[#152033] animate-in fade-in slide-in-from-bottom-1">
              <button
                type="button"
                onClick={() => {
                  fileInputRef.current?.click();
                  setIsPlusMenuOpen(false);
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left hover:bg-[#F1F5FB] text-[#152033] transition-colors cursor-pointer"
              >
                <Paperclip className="w-3.5 h-3.5 text-[#667085]" />
                <span>Attach text file</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setIsPlusMenuOpen(false);
                  setShowShortcutsModal(true);
                }}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left hover:bg-[#F1F5FB] text-[#152033] transition-colors cursor-pointer"
              >
                <Keyboard className="w-3.5 h-3.5 text-[#667085]" />
                <span>Keyboard shortcuts</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  setInputValue('');
                  setIsPlusMenuOpen(false);
                }}
                disabled={!inputValue}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left hover:bg-[#F1F5FB] text-[#152033] disabled:text-[#A0AEC0] disabled:cursor-not-allowed transition-colors cursor-pointer"
              >
                <Trash2 className="w-3.5 h-3.5 text-[#667085]" />
                <span>Clear draft</span>
              </button>
            </div>
          )}
        </div>

        {/* Flexible Text Input */}
        <form onSubmit={handleSendMessage} className="flex-1 flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
              }
            }}
            placeholder={
              activeMode === 'task'
                ? 'State high-level goal to decompose into execution graph (e.g. Audit repo, run checks, stage PR)...'
                : activeMode === 'memory'
                ? 'Search episodic saga logs or semantic rules (e.g. user preferences, rules, decisions)...'
                : 'Ask anything...'
            }
            rows={1}
            className="flex-1 bg-transparent border-0 text-[14px] sm:text-[15px] text-[#152033] placeholder:text-[#8E95A2] resize-none px-2 py-1.5 focus:ring-0 focus:outline-none font-sans leading-relaxed min-h-[36px] max-h-[160px]"
          />

          {/* Icon-Only Send Control (Circular on the right) */}
          <button
            type="submit"
            disabled={!inputValue.trim() || isSending}
            aria-label="Send message"
            title="Send message"
            className="flex h-8 w-8 sm:h-9 sm:w-9 shrink-0 items-center justify-center rounded-full bg-[#14213D] text-white hover:bg-[#22375C] active:scale-95 disabled:opacity-30 disabled:hover:bg-[#14213D] disabled:active:scale-100 disabled:cursor-not-allowed transition-all mb-0.5 cursor-pointer shadow-xs"
          >
            {isSending ? (
              <RefreshCw className="w-4 h-4 animate-spin text-white" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </form>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col h-screen bg-[#F7F9FC] text-[#152033] overflow-hidden">
      {/* Top Navigation Bar with Combined Runtime Status Indicators */}
      <AppSidebar
        pendingApprovalsCount={
          messages.some(
            (m) => m.actionProposal && m.actionProposal.status === 'pending'
          )
            ? 1
            : 0
        }
        ollamaStatus={runtimeStatus?.ollamaStatus || (isBackendOnline ? 'connected' : 'disconnected')}
        isBackendOnline={isBackendOnline}
        isInferenceActive={isSending || (isBackendOnline && runtimeStatus?.ollamaStatus === 'connected')}
        onRefreshBackend={probeBackend}
        isChecking={isCheckingBackend}
      />

      {/* Main Conversation Area */}
      <main className="flex-1 flex flex-col max-w-4xl w-full mx-auto px-4 sm:px-6 overflow-hidden">
        {messages.length === 0 ? (
          /* Empty Initial State: Subtitle and Composer Centered in Available Canvas */
          <div className="flex-1 flex flex-col items-center justify-center -mt-10 w-full px-2">
            <h2 className="mb-4 text-center text-[15px] sm:text-[17px] font-semibold tracking-tight text-[#14213D]">
              Sovereign orchestrator running on local Ollama stack
            </h2>
            {renderModeTabs()}
            {renderComposer()}
          </div>
        ) : (
          /* Active Conversation State */
          <div className="flex-1 flex flex-col h-full overflow-hidden">
            {/* Scrollable Conversation Stream */}
            <div className="flex-1 overflow-y-auto space-y-5 px-1 py-4">
              {messages.map((msg) => {
                const isUser = msg.role === 'user';
                const isSystem = msg.role === 'system';
                const isTraceExpanded = expandedTraceId === msg.id;

                if (isSystem) {
                  return (
                    <div
                      key={msg.id}
                      className="mx-auto max-w-lg p-2 rounded-lg text-xs font-mono text-[#8792A5] text-center"
                    >
                      {msg.content}
                    </div>
                  );
                }

                if (isUser) {
                  return (
                    <div key={msg.id} className="flex justify-end w-full">
                      <div className="max-w-[85%] sm:max-w-xl rounded-2xl bg-[#EEF0F3] px-4 py-2.5 text-[14px] sm:text-[15px] leading-relaxed text-[#152033] ml-auto">
                        <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                        <div
                          className="mt-1 text-right text-[10px] font-mono text-[#8792A5] select-none"
                          suppressHydrationWarning
                        >
                          {msg.timestamp}
                        </div>
                      </div>
                    </div>
                  );
                }

                // Assistant Output: Clean unboxed canvas presentation
                const hasAuditMetadata =
                  (msg.citedMemoryIds && msg.citedMemoryIds.length > 0) ||
                  Boolean(msg.thoughtTrace);

                return (
                  <div key={msg.id} className="flex flex-col items-start w-full max-w-3xl space-y-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[#8792A5]">
                      Assistant
                    </span>

                    <div className="w-full text-[14px] sm:text-[15px] leading-relaxed text-[#152033]">
                      <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                    </div>

                    {/* 3-Dots disclosure for Memory Recall & Reasoning Trace */}
                    {hasAuditMetadata && (
                      <div className="w-full pt-0.5">
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedTraceId(isTraceExpanded ? null : msg.id)
                          }
                          aria-label="Toggle Memory Recall and Reasoning Trace"
                          title="Memory Recall & Reasoning Trace"
                          className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[#8792A5] hover:text-[#14213D] hover:bg-[#EEF0F3] transition-colors cursor-pointer text-xs"
                        >
                          <MoreHorizontal className="w-4 h-4" />
                          <span className="text-[11px] font-mono text-[#8792A5]">
                            {isTraceExpanded ? 'Hide details' : 'Memory recall & trace'}
                          </span>
                        </button>

                        {isTraceExpanded && (
                          <div className="mt-2 w-full space-y-2.5 rounded-xl bg-white border border-[#E2E8F0] p-3 shadow-xs text-xs animate-in fade-in">
                            {/* Cited Memory Tags */}
                            {msg.citedMemoryIds && msg.citedMemoryIds.length > 0 && (
                              <div className="flex flex-wrap items-center gap-1.5 pb-2 border-b border-[#F0F2F6]">
                                <span className="text-[10px] font-mono uppercase font-semibold text-[#8792A5]">
                                  Memory Recall:
                                </span>
                                {msg.citedMemoryIds.map((memId) => (
                                  <span
                                    key={memId}
                                    className="text-[10px] font-mono bg-yellow-50 border border-yellow-300 text-yellow-900 px-1.5 py-0.5 rounded font-medium"
                                  >
                                    #{memId}
                                  </span>
                                ))}
                              </div>
                            )}

                            {/* Reasoning Trace */}
                            {msg.thoughtTrace && (
                              <div className="space-y-1">
                                <div className="flex items-center gap-1.5 font-mono text-[11px] font-semibold text-yellow-950">
                                  <Sparkles className="w-3.5 h-3.5 text-yellow-600" />
                                  <span>Reasoning Trace</span>
                                </div>
                                <div className="p-2.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] font-mono text-zinc-700 text-xs whitespace-pre-wrap leading-relaxed">
                                  {msg.thoughtTrace}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Embedded Action Proposal (Approval Gate) */}
                    {msg.actionProposal && (
                      <Card className="w-full border-amber-300 bg-amber-50/70 p-4 space-y-3 shadow-xs mt-2">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-2.5">
                            <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-bold text-amber-950">
                                  Gatekeeper Approval Required
                                </span>
                                <Badge variant="amber" dot className="text-[10px]">
                                  {msg.actionProposal.riskLevel.toUpperCase()} RISK
                                </Badge>
                              </div>
                              <p className="mt-0.5 text-xs font-medium text-zinc-900">
                                {msg.actionProposal.actionTitle}
                              </p>
                              <p className="mt-0.5 text-[11px] text-zinc-600">
                                {msg.actionProposal.description}
                              </p>
                            </div>
                          </div>

                          <span className="font-mono text-[11px] text-zinc-500 uppercase bg-white px-1.5 py-0.5 rounded border border-zinc-200">
                            {msg.actionProposal.toolName}
                          </span>
                        </div>

                        <div className="flex items-center justify-end gap-2 pt-2 border-t border-amber-200">
                          {msg.actionProposal.status === 'pending' ? (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  const appr = DEMO_APPROVALS.find(
                                    (a) => a.id === msg.actionProposal?.id
                                  );
                                  if (appr) setActiveApproval(appr);
                                }}
                                className="text-xs border-amber-300 text-amber-950 hover:bg-amber-100 bg-white"
                              >
                                Inspect Parameters
                              </Button>
                              <Button
                                size="sm"
                                variant="primary"
                                onClick={() =>
                                  handleResolveApproval(msg.actionProposal!.id, 'approved')
                                }
                                icon={<Check className="w-3.5 h-3.5" />}
                              >
                                Authorize
                              </Button>
                            </>
                          ) : (
                            <Badge
                              variant={
                                msg.actionProposal.status === 'approved'
                                  ? 'emerald'
                                  : 'rose'
                              }
                            >
                              Status: {msg.actionProposal.status.toUpperCase()}
                            </Badge>
                          )}
                        </div>
                      </Card>
                    )}
                  </div>
                );
              })}
              <div ref={messagesEndRef} />
            </div>

            {/* Subtitle centered immediately above composer during active conversation */}
            <div className="text-center pb-2 pt-1">
              <p className="text-[12px] sm:text-[13px] font-medium tracking-tight text-[#667085]">
                Sovereign orchestrator running on local Ollama stack
              </p>
              <div className="mt-2">
                {renderModeTabs()}
              </div>
            </div>

            {/* Composer anchored at bottom */}
            <div className="pb-4">
              {renderComposer()}
            </div>
          </div>
        )}
      </main>

      {/* Keyboard Shortcuts Dialog */}
      {showShortcutsModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="shortcuts-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4"
        >
          <div className="w-full max-w-sm rounded-2xl border border-[#E4E9F1] bg-white p-5 shadow-xl animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between pb-3 border-b border-[#E4E9F1]">
              <h3 id="shortcuts-title" className="text-sm font-semibold text-[#14213D] flex items-center gap-2">
                <Keyboard className="w-4 h-4 text-[#667085]" />
                Keyboard Shortcuts
              </h3>
              <button
                type="button"
                onClick={() => setShowShortcutsModal(false)}
                className="text-[#8792A5] hover:text-[#14213D] text-xs font-bold p-1 cursor-pointer"
              >
                ✕
              </button>
            </div>
            <div className="py-4 space-y-2.5 text-xs text-[#4B5563]">
              <div className="flex items-center justify-between">
                <span>Send message</span>
                <kbd className="px-2 py-0.5 rounded bg-[#F7F9FC] border border-[#E4E9F1] font-mono text-[11px] text-[#14213D]">
                  Enter
                </kbd>
              </div>
              <div className="flex items-center justify-between">
                <span>New line in prompt</span>
                <kbd className="px-2 py-0.5 rounded bg-[#F7F9FC] border border-[#E4E9F1] font-mono text-[11px] text-[#14213D]">
                  Shift + Enter
                </kbd>
              </div>
              <div className="flex items-center justify-between">
                <span>Dismiss menu / modal</span>
                <kbd className="px-2 py-0.5 rounded bg-[#F7F9FC] border border-[#E4E9F1] font-mono text-[11px] text-[#14213D]">
                  Esc
                </kbd>
              </div>
            </div>
            <div className="pt-2 text-right">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowShortcutsModal(false)}
              >
                Close
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Interactive Approval Modal */}
      <ApprovalModal
        request={activeApproval}
        isOpen={Boolean(activeApproval)}
        onClose={() => setActiveApproval(null)}
        onResolve={handleResolveApproval}
      />
    </div>
  );
}
