'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
  Check,
  Sparkles,
  Bot,
  User,
  MoreHorizontal,
  Keyboard,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import { AppSidebar } from '@/components/shell/AppSidebar';
import { AppHeader } from '@/components/shell/AppHeader';
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
import { DEMO_CHAT_MESSAGES, DEMO_APPROVALS } from '@/lib/api/fixtures';

export default function CommandCenterPage() {
  const [messages, setMessages] = useState<ChatMessage[]>(DEMO_CHAT_MESSAGES);
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [activeMode, setActiveMode] = useState<'chat' | 'task' | 'memory'>('chat');
  const [expandedTraceId, setExpandedTraceId] = useState<string | null>(null);

  // Composer 3-dot overflow menu & shortcuts modal states
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [showShortcutsModal, setShowShortcutsModal] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsMenuOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsMenuOpen(false);
        setShowShortcutsModal(false);
      }
    };
    if (isMenuOpen || showShortcutsModal) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isMenuOpen, showShortcutsModal]);

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

    try {
      const response = await api.sendPrompt(userText, activeMode);
      setMessages((prev) => [...prev, response.data]);
    } catch {
      // Local fallback in case of catastrophic network trap
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
    // Update local proposal state in chat message if present
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

  return (
    <div className="flex flex-col h-screen bg-[#F7F9FC] text-[#152033] overflow-hidden">
      {/* Top Navigation Bar */}
      <AppSidebar
        pendingApprovalsCount={
          messages.some(
            (m) => m.actionProposal && m.actionProposal.status === 'pending'
          )
            ? 1
            : 0
        }
        ollamaStatus={runtimeStatus?.ollamaStatus || (isBackendOnline ? 'connected' : 'disconnected')}
      />

      {/* Clean Top Status & Centered Heading Area */}
      <AppHeader
        title="Command Center"
        subtitle="Sovereign orchestrator running on local Ollama stack"
        centered={true}
        isBackendOnline={isBackendOnline}
        isChecking={isCheckingBackend}
        onRefreshBackend={probeBackend}
        ollamaStatus={runtimeStatus?.ollamaStatus || (isBackendOnline ? 'connected' : 'disconnected')}
        isInferenceActive={isSending || (isBackendOnline && runtimeStatus?.ollamaStatus === 'connected')}
      />

      {/* Command Center Chat Canvas */}
      <main className="flex-1 flex flex-col max-w-5xl w-full mx-auto p-4 sm:p-6 overflow-hidden">
        {/* Conversation Stream */}
          <div className="flex-1 overflow-y-auto space-y-4 pr-1 mb-4">
            {messages.map((msg) => {
              const isUser = msg.role === 'user';
              const isSystem = msg.role === 'system';
              const isTraceExpanded = expandedTraceId === msg.id;

              if (isSystem) {
                return (
                  <div
                    key={msg.id}
                    className="p-3 rounded-lg bg-[#F4F3EE] border border-[#E5E3DC] text-xs font-mono text-zinc-600 text-center"
                  >
                    {msg.content}
                  </div>
                );
              }

              return (
                <div
                  key={msg.id}
                  className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}
                >
                  {!isUser && (
                    <div className="w-8 h-8 rounded-lg bg-yellow-400 border border-yellow-500/40 flex items-center justify-center text-zinc-950 shrink-0 text-xs font-mono font-black mt-1 shadow-2xs">
                      81
                    </div>
                  )}

                  <div className={`max-w-2xl space-y-2 ${isUser ? 'items-end' : ''}`}>
                    <div
                      className={`p-4 rounded-xl text-sm leading-relaxed ${
                        isUser
                          ? 'bg-zinc-950 text-white border border-zinc-900 ml-auto shadow-xs font-medium'
                          : 'bg-white text-zinc-900 border border-[#E5E3DC] shadow-xs'
                      }`}
                    >
                      <div className={`flex items-center justify-between gap-4 mb-1.5 text-[11px] font-mono ${isUser ? 'text-zinc-400' : 'text-zinc-500'}`}>
                        <span className="flex items-center gap-1 font-semibold">
                          {isUser ? <User className="w-3 h-3" /> : <Bot className="w-3 h-3 text-zinc-700" />}
                          {isUser ? 'You' : 'Go 81 Assistant'}
                        </span>
                        <span suppressHydrationWarning>{msg.timestamp}</span>
                      </div>

                      <p className="whitespace-pre-wrap">{msg.content}</p>

                      {/* Cited Memory Tags */}
                      {msg.citedMemoryIds && msg.citedMemoryIds.length > 0 && (
                        <div className={`mt-3 pt-2 border-t ${isUser ? 'border-zinc-800' : 'border-zinc-100'} flex flex-wrap items-center gap-1.5`}>
                          <span className={`text-[10px] font-mono uppercase font-semibold ${isUser ? 'text-zinc-400' : 'text-zinc-500'}`}>
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
                    </div>

                    {/* Expandable Reasoning Trace (NFR4.1 Explainability) */}
                    {msg.thoughtTrace && (
                      <div className="rounded-lg bg-yellow-50/70 border border-yellow-200/90 overflow-hidden text-xs shadow-2xs">
                        <button
                          onClick={() =>
                            setExpandedTraceId(isTraceExpanded ? null : msg.id)
                          }
                          className="w-full px-3 py-1.5 flex items-center justify-between text-yellow-950 hover:bg-yellow-100/50 cursor-pointer font-mono text-[11px] font-semibold transition-colors"
                        >
                          <span className="flex items-center gap-1.5">
                            <Sparkles className="w-3 h-3 text-yellow-600" />
                            Reasoning Trace
                          </span>
                          {isTraceExpanded ? (
                            <ChevronUp className="w-3.5 h-3.5 text-yellow-700" />
                          ) : (
                            <ChevronDown className="w-3.5 h-3.5 text-yellow-700" />
                          )}
                        </button>

                        {isTraceExpanded && (
                          <div className="p-3 border-t border-yellow-200 bg-white/80 font-mono text-zinc-700 text-xs whitespace-pre-wrap leading-relaxed">
                            {msg.thoughtTrace}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Embedded Action Proposal (FR4.3 Approval Gate) */}
                    {msg.actionProposal && (
                      <Card className="border-amber-300 bg-amber-50/70 p-4 space-y-3 shadow-xs">
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
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          {/* Redesigned Minimal Chat Composer */}
          <div className="relative rounded-2xl border border-[#E4E9F1] bg-white p-3 shadow-xs transition-all focus-within:border-[#14213D] focus-within:ring-1 focus-within:ring-[#14213D]/10">
            {/* Composer Header: Identity + Text-Only Tabs + 3-Dot Menu */}
            <div className="flex items-center justify-between gap-2 px-1 pb-2">
              <div className="flex flex-wrap items-center gap-3 sm:gap-4 min-w-0">
                {/* Go 81 Assistant Identity */}
                <div className="flex items-center gap-1.5 text-xs font-medium text-[#14213D] shrink-0 select-none">
                  <Bot className="w-3.5 h-3.5 text-[#14213D]" />
                  <span>Go 81 Assistant</span>
                </div>

                <span className="text-[#D0D5DD] select-none hidden sm:inline" aria-hidden="true">
                  |
                </span>

                {/* Text-Only Mode Navigation Controls */}
                <div className="flex items-center gap-3 sm:gap-4 text-xs font-medium">
                  <button
                    type="button"
                    onClick={() => setActiveMode('chat')}
                    className={`cursor-pointer transition-colors pb-0.5 ${
                      activeMode === 'chat'
                        ? 'text-[#14213D] font-semibold border-b-2 border-[#14213D]'
                        : 'text-[#667085] hover:text-[#14213D] border-b-2 border-transparent'
                    }`}
                  >
                    Chat &amp; Query
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveMode('task')}
                    className={`cursor-pointer transition-colors pb-0.5 ${
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
                    className={`cursor-pointer transition-colors pb-0.5 ${
                      activeMode === 'memory'
                        ? 'text-[#14213D] font-semibold border-b-2 border-[#14213D]'
                        : 'text-[#667085] hover:text-[#14213D] border-b-2 border-transparent'
                    }`}
                  >
                    Semantic Memory Search
                  </button>
                </div>
              </div>

              {/* Three-Dot Composer Overflow Menu */}
              <div className="relative shrink-0" ref={menuRef}>
                <button
                  type="button"
                  onClick={() => setIsMenuOpen((prev) => !prev)}
                  aria-label="Composer options"
                  title="Composer options"
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-[#667085] hover:bg-[#F1F5FB] hover:text-[#14213D] transition-colors cursor-pointer"
                >
                  <MoreHorizontal className="w-4 h-4" />
                </button>

                {/* Popup Menu */}
                {isMenuOpen && (
                  <div className="absolute right-0 top-full mt-1.5 w-48 rounded-xl border border-[#E4E9F1] bg-white p-1 shadow-lg z-30 text-xs text-[#152033] animate-in fade-in slide-in-from-top-1">
                    <button
                      type="button"
                      onClick={() => {
                        setIsMenuOpen(false);
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
                        setIsMenuOpen(false);
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
            </div>

            {/* Input & Send Action (No nested borders, no dividing line) */}
            <form onSubmit={handleSendMessage} className="flex items-end gap-2 pt-1">
              <textarea
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
                    : 'Dispatch instruction to sovereign personal agent...'
                }
                rows={2}
                className="flex-1 bg-transparent border-0 text-xs sm:text-sm text-[#152033] placeholder:text-[#94A3B8] resize-none px-1 py-1 focus:ring-0 focus:outline-none font-sans leading-relaxed"
              />

              {/* Minimal Icon-Only Send Control */}
              <button
                type="submit"
                disabled={!inputValue.trim() || isSending}
                aria-label="Send message"
                title="Send message"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#14213D] text-white hover:bg-[#22375C] active:scale-95 disabled:opacity-35 disabled:hover:bg-[#14213D] disabled:active:scale-100 disabled:cursor-not-allowed transition-all mb-0.5 cursor-pointer shadow-xs"
              >
                {isSending ? (
                  <RefreshCw className="w-4 h-4 animate-spin text-white" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
              </button>
            </form>
          </div>
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
