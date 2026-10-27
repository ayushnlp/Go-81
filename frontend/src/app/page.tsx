'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
  Brain,
  Check,
  Sparkles,
  ArrowUpRight,
  ShieldCheck,
  Bot,
  User,
} from 'lucide-react';
import { AppSidebar } from '@/components/shell/AppSidebar';
import { AppHeader } from '@/components/shell/AppHeader';
import { OfflineBanner } from '@/components/ui/OfflineBanner';
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

  const starters = [
    'Triage project inbox and stage obligation checklist',
    'Audit local network sockets for sovereign privacy guarantee',
    'Run Norns memory consolidation and prune obsolete traces',
  ];

  return (
    <div className="flex min-h-screen bg-[#090b0e] text-zinc-100">
      {/* Persistent Application Shell Sidebar */}
      <AppSidebar
        pendingApprovalsCount={
          messages.some(
            (m) => m.actionProposal && m.actionProposal.status === 'pending'
          )
            ? 1
            : 0
        }
        ollamaStatus={runtimeStatus?.ollamaStatus || 'connected'}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Offline / Staging Notification Banner */}
        <OfflineBanner
          isLive={isBackendOnline}
          isChecking={isCheckingBackend}
          onRetry={probeBackend}
          backendUrl={api.getBaseUrl()}
        />

        <AppHeader
          title="Command Center"
          subtitle="Sovereign orchestrator running on local Ollama stack"
          isBackendOnline={isBackendOnline}
          isChecking={isCheckingBackend}
          onRefreshBackend={probeBackend}
        />

        {/* Command Center Chat Canvas */}
        <main className="flex-1 flex flex-col max-w-5xl w-full mx-auto p-4 sm:p-6 overflow-hidden">
          {/* Active Runtime Header Pill */}
          <div className="mb-4 p-3 rounded-xl bg-[#101319] border border-zinc-800/80 flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 font-mono text-zinc-300">
                <Bot className="w-4 h-4 text-emerald-400" />
                {runtimeStatus?.model || 'llama3.2:3b-instruct-q8_0'}
              </span>
              <span className="text-zinc-600">|</span>
              <span className="flex items-center gap-1.5 font-mono text-zinc-400">
                <Brain className="w-3.5 h-3.5 text-sky-400" />
                1,428 Mimir Runes Active
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800/40 px-2 py-0.5 rounded flex items-center gap-1">
                <ShieldCheck className="w-3 h-3" />
                0 KB Telemetry
              </span>
            </div>
          </div>

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
                    className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-850 text-xs font-mono text-zinc-400 text-center"
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
                    <div className="w-8 h-8 rounded-lg bg-emerald-950/80 border border-emerald-500/40 flex items-center justify-center text-emerald-400 shrink-0 text-xs font-mono font-bold mt-1">
                      ᚱ
                    </div>
                  )}

                  <div className={`max-w-2xl space-y-2 ${isUser ? 'items-end' : ''}`}>
                    <div
                      className={`p-4 rounded-xl text-sm leading-relaxed ${
                        isUser
                          ? 'bg-zinc-800/90 text-zinc-100 border border-zinc-700/60 ml-auto'
                          : 'bg-[#11141C] text-zinc-200 border border-zinc-800/90 shadow-md'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-4 mb-1.5 text-[11px] font-mono text-zinc-500">
                        <span className="flex items-center gap-1">
                          {isUser ? <User className="w-3 h-3" /> : <Bot className="w-3 h-3" />}
                          {isUser ? 'You' : 'Go 81 Assistant'}
                        </span>
                        <span>{msg.timestamp}</span>
                      </div>

                      <p className="whitespace-pre-wrap">{msg.content}</p>

                      {/* Cited Memory Tags */}
                      {msg.citedMemoryIds && msg.citedMemoryIds.length > 0 && (
                        <div className="mt-3 pt-2 border-t border-zinc-800/60 flex flex-wrap items-center gap-1.5">
                          <span className="text-[10px] font-mono text-zinc-500 uppercase">
                            Mimir Recall:
                          </span>
                          {msg.citedMemoryIds.map((memId) => (
                            <span
                              key={memId}
                              className="text-[10px] font-mono bg-zinc-900 border border-zinc-750 text-sky-400 px-1.5 py-0.5 rounded"
                            >
                              #{memId}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Expandable Seer's Telling / Reasoning Trace (NFR4.1 Explainability) */}
                    {msg.thoughtTrace && (
                      <div className="rounded-lg bg-zinc-950/70 border border-zinc-850 overflow-hidden text-xs">
                        <button
                          onClick={() =>
                            setExpandedTraceId(isTraceExpanded ? null : msg.id)
                          }
                          className="w-full px-3 py-1.5 flex items-center justify-between text-zinc-400 hover:text-zinc-200 cursor-pointer font-mono text-[11px]"
                        >
                          <span className="flex items-center gap-1.5 text-emerald-400/90">
                            <Sparkles className="w-3 h-3" />
                            Seer&apos;s Telling (Reasoning Trace)
                          </span>
                          {isTraceExpanded ? (
                            <ChevronUp className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronDown className="w-3.5 h-3.5" />
                          )}
                        </button>

                        {isTraceExpanded && (
                          <div className="p-3 border-t border-zinc-850 bg-black/40 font-mono text-zinc-400 text-xs whitespace-pre-wrap leading-relaxed">
                            {msg.thoughtTrace}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Embedded Action Proposal (FR4.3 Approval Gate) */}
                    {msg.actionProposal && (
                      <Card className="border-amber-800/40 bg-amber-950/15 p-4 space-y-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-2.5">
                            <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-semibold text-amber-200">
                                  Gatekeeper Approval Required
                                </span>
                                <Badge variant="amber" dot className="text-[10px]">
                                  {msg.actionProposal.riskLevel.toUpperCase()} RISK
                                </Badge>
                              </div>
                              <p className="mt-0.5 text-xs text-zinc-300">
                                {msg.actionProposal.actionTitle}
                              </p>
                              <p className="mt-0.5 text-[11px] text-zinc-400">
                                {msg.actionProposal.description}
                              </p>
                            </div>
                          </div>

                          <span className="font-mono text-[11px] text-zinc-500 uppercase">
                            {msg.actionProposal.toolName}
                          </span>
                        </div>

                        <div className="flex items-center justify-end gap-2 pt-1 border-t border-amber-900/30">
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
                                className="text-xs border-amber-700/50 text-amber-300 hover:bg-amber-950/40"
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

          {/* Quick Action Starters */}
          {messages.length <= 4 && (
            <div className="mb-3 flex flex-wrap gap-2">
              {starters.map((starter, i) => (
                <button
                  key={i}
                  onClick={() => setInputValue(starter)}
                  className="px-3 py-1.5 rounded-lg bg-[#11141C] border border-zinc-800 hover:border-zinc-700 text-xs text-zinc-400 hover:text-zinc-200 text-left transition-colors flex items-center gap-1.5 cursor-pointer"
                >
                  <ArrowUpRight className="w-3 h-3 text-emerald-400 shrink-0" />
                  <span>{starter}</span>
                </button>
              ))}
            </div>
          )}

          {/* Multi-Mode Prompt Input Bar */}
          <div className="rounded-xl bg-[#11141C] border border-zinc-800 shadow-xl overflow-hidden p-2">
            {/* Mode Selector */}
            <div className="px-2 py-1 flex items-center justify-between border-b border-zinc-800/60 pb-2 mb-2 text-xs">
              <div className="flex items-center gap-1 font-mono text-[11px]">
                <button
                  type="button"
                  onClick={() => setActiveMode('chat')}
                  className={`px-2 py-1 rounded cursor-pointer ${
                    activeMode === 'chat'
                      ? 'bg-zinc-800 text-zinc-100 font-semibold'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  Chat &amp; Query
                </button>
                <button
                  type="button"
                  onClick={() => setActiveMode('task')}
                  className={`px-2 py-1 rounded cursor-pointer ${
                    activeMode === 'task'
                      ? 'bg-zinc-800 text-zinc-100 font-semibold'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  Autonomous Workflow
                </button>
                <button
                  type="button"
                  onClick={() => setActiveMode('memory')}
                  className={`px-2 py-1 rounded cursor-pointer ${
                    activeMode === 'memory'
                      ? 'bg-zinc-800 text-zinc-100 font-semibold'
                      : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  Mimir Memory Recall
                </button>
              </div>

              <span className="text-[10px] font-mono text-zinc-500 hidden sm:inline">
                Shift + Enter for new line
              </span>
            </div>

            {/* Input & Action */}
            <form onSubmit={handleSendMessage} className="flex items-end gap-2">
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
                    ? 'Search episodic saga logs or semantic rules (e.g. hackathon submission invariants)...'
                    : 'Dispatch instruction to sovereign personal agent...'
                }
                rows={2}
                className="flex-1 bg-transparent border-0 text-sm text-zinc-100 placeholder-zinc-500 resize-none px-2 py-1 focus:ring-0 focus:outline-none font-sans"
              />

              <Button
                type="submit"
                variant="primary"
                size="md"
                disabled={!inputValue.trim()}
                loading={isSending}
                icon={<Send className="w-4 h-4" />}
                className="shrink-0 mb-1"
              >
                Send
              </Button>
            </form>
          </div>
        </main>
      </div>

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
