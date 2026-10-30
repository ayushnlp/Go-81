'use client';

import React, { useState, useEffect } from 'react';
import {
  Wrench,
  Shield,
  ShieldAlert,
  Play,
  Terminal,
  Cpu,
  FolderTree,
  Mail,
  Code2,
  Check,
  RefreshCw,
  Search,
  Eye,
  X,
  Layers,
} from 'lucide-react';
import { api } from '@/lib/api/client';
import { SkillDefinition, SkillCategory } from '@/lib/api/types';

const categoryIcons: Record<SkillCategory, React.ElementType> = {
  system: Cpu,
  filesystem: FolderTree,
  network: Terminal,
  communication: Mail,
  developer: Code2,
};

export const SkillsWorkspace: React.FC = () => {
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<'all' | SkillCategory>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [inspectingSkill, setInspectingSkill] = useState<SkillDefinition | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchSkills = async () => {
    setIsLoading(true);
    try {
      const res = await api.getSkills();
      setSkills(res.data || []);
    } catch {
      // offline fallback
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSkills();
  }, []);

  const filteredSkills = skills.filter((s) => {
    if (selectedCategory !== 'all' && s.category !== selectedCategory) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        s.name.toLowerCase().includes(q) ||
        (s.displayName && s.displayName.toLowerCase().includes(q)) ||
        (s.description && s.description.toLowerCase().includes(q))
      );
    }
    return true;
  });

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[var(--bg-canvas)]">
      {/* Top Filter and Actions Toolbar */}
      <div className="px-6 py-4 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0 flex flex-wrap items-center justify-between gap-4 select-none">
        {/* Category Pills */}
        <div className="flex items-center space-x-1.5 overflow-x-auto text-xs font-medium">
          {(['all', 'system', 'filesystem', 'network', 'communication', 'developer'] as const).map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setSelectedCategory(cat)}
              className={`px-3 py-1.5 rounded-full capitalize transition-colors cursor-pointer ${
                selectedCategory === cat
                  ? 'bg-[#ea580c] text-white font-semibold shadow-xs'
                  : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border-subtle)]'
              }`}
            >
              {cat === 'all' ? `All (${skills.length})` : cat}
            </button>
          ))}
        </div>

        {/* Right Tools: Search & Refresh */}
        <div className="flex items-center space-x-2">
          <div className="flex items-center px-3 py-1.5 rounded-full bg-[var(--bg-canvas)] border border-[var(--border-subtle)] focus-within:border-[#ea580c] transition-colors w-48 sm:w-60">
            <Search className="w-3.5 h-3.5 text-[var(--text-muted)] mr-2 shrink-0" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter skills..."
              className="w-full bg-transparent text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none"
            />
          </div>

          <button
            type="button"
            onClick={fetchSkills}
            disabled={isLoading}
            title="Refresh skills registry"
            className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-secondary)] border border-[var(--border-subtle)] transition-colors cursor-pointer shadow-2xs"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main Grid: Skills Cards */}
      <div className="flex-1 overflow-y-auto p-6 md:p-8">
        <div className="max-w-6xl mx-auto space-y-4">
          <div className="flex items-center justify-between text-xs text-[var(--text-muted)] px-1 select-none">
            <span>Stage 3 & 4 Registered Toolchain • Sandbox Enforced</span>
            <span>{filteredSkills.length} registered skill{filteredSkills.length === 1 ? '' : 's'}</span>
          </div>

          {filteredSkills.length === 0 ? (
            <div className="text-center py-20 text-[var(--text-muted)] text-sm space-y-1 select-none">
              <Wrench className="w-8 h-8 text-[var(--text-muted)] opacity-40 mx-auto mb-2" />
              <p className="font-semibold text-[var(--text-primary)]">No matching skills found</p>
              <p className="text-xs">All registered actions are sandboxed with default-deny verification.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredSkills.map((skill) => {
                const IconComponent = categoryIcons[skill.category] || Wrench;
                const isHighRisk = skill.riskLevel === 'high' || skill.riskLevel === 'critical';

                return (
                  <div
                    key={skill.id}
                    className="p-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:border-[var(--accent-primary-border)] shadow-2xs transition-all flex flex-col justify-between space-y-3"
                  >
                    <div className="space-y-2.5">
                      {/* Card Header */}
                      <div className="flex items-start justify-between">
                        <div className="flex items-center space-x-2.5 truncate mr-2">
                          <div className="p-2 rounded-lg bg-[var(--bg-elevated)] text-[#ea580c] shrink-0">
                            <IconComponent className="w-4 h-4" />
                          </div>
                          <div className="truncate">
                            <h4 className="text-xs font-bold text-[var(--text-primary)] truncate font-mono">
                              {skill.displayName || skill.name}
                            </h4>
                            <span className="text-[10px] text-[var(--text-muted)] font-mono block">
                              {skill.isSandboxed ? 'Sandboxed' : 'Host'}
                            </span>
                          </div>
                        </div>

                        {/* Risk Badge */}
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase shrink-0 ${
                          isHighRisk
                            ? 'bg-rose-500/10 text-rose-500 border border-rose-500/20'
                            : 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20'
                        }`}>
                          {skill.riskLevel}
                        </span>
                      </div>

                      {/* Description */}
                      <p className="text-xs text-[var(--text-secondary)] line-clamp-2 leading-relaxed">
                        {skill.description || 'No description provided.'}
                      </p>

                      {/* Capabilities / Parameters pills */}
                      <div className="flex flex-wrap gap-1 pt-1">
                        {skill.parameters.slice(0, 3).map((param) => (
                          <span
                            key={param.name}
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-muted)] border border-[var(--border-subtle)]"
                          >
                            {param.name}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Bottom Action Footer */}
                    <div className="pt-3 border-t border-[var(--border-subtle)] flex items-center justify-between text-xs">
                      <div className="flex items-center space-x-2">
                        {skill.requiresApproval ? (
                          <span className="flex items-center space-x-1 text-[11px] text-amber-500 font-semibold">
                            <ShieldAlert className="w-3.5 h-3.5" />
                            <span>Approval Req.</span>
                          </span>
                        ) : (
                          <span className="flex items-center space-x-1 text-[11px] text-emerald-500 font-medium">
                            <Shield className="w-3.5 h-3.5" />
                            <span>Auto-Approved</span>
                          </span>
                        )}
                      </div>

                      <button
                        type="button"
                        onClick={() => setInspectingSkill(skill)}
                        className="flex items-center space-x-1 text-xs text-[var(--text-secondary)] hover:text-[#ea580c] transition-colors cursor-pointer font-medium"
                      >
                        <Eye className="w-3.5 h-3.5" />
                        <span>Inspect</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Inspect Skill Schema Modal */}
      {inspectingSkill && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="w-full max-w-xl rounded-2xl bg-[var(--bg-surface)] border border-[var(--border-subtle)] p-6 shadow-2xl space-y-4 max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)] shrink-0">
              <div className="flex items-center space-x-2.5">
                <Wrench className="w-4 h-4 text-[#ea580c]" />
                <div>
                  <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                    {inspectingSkill.displayName || inspectingSkill.name}
                  </h3>
                  <span className="text-[10px] text-[var(--text-muted)] font-mono">
                    ID: {inspectingSkill.id} • Sandbox: {inspectingSkill.isSandboxed ? 'Active' : 'Disabled'}
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setInspectingSkill(null)}
                className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-3.5 text-xs pr-1">
              <div>
                <span className="font-semibold text-[var(--text-muted)] uppercase tracking-wider text-[10px] block mb-1">
                  Description
                </span>
                <p className="text-[var(--text-secondary)] leading-relaxed p-2.5 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)]">
                  {inspectingSkill.description}
                </p>
              </div>

              <div>
                <span className="font-semibold text-[var(--text-muted)] uppercase tracking-wider text-[10px] block mb-1">
                  Parameters Schema ({inspectingSkill.parameters.length})
                </span>
                <div className="space-y-1.5">
                  {inspectingSkill.parameters.map((p) => (
                    <div
                      key={p.name}
                      className="p-2.5 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] flex items-start justify-between"
                    >
                      <div>
                        <div className="flex items-center space-x-2">
                          <span className="font-mono font-bold text-[var(--text-primary)]">{p.name}</span>
                          <span className="font-mono text-[10px] text-[var(--text-muted)]">({p.type})</span>
                          {p.required && (
                            <span className="text-[9px] font-bold text-rose-500 uppercase">Required</span>
                          )}
                        </div>
                        {p.description && (
                          <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">{p.description}</p>
                        )}
                      </div>
                      {p.default !== undefined && (
                        <span className="text-[10px] font-mono text-[var(--text-muted)] shrink-0">
                          default: {JSON.stringify(p.default)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <span className="font-semibold text-[var(--text-muted)] uppercase tracking-wider text-[10px] block mb-1">
                  Execution Policy & Guardrails
                </span>
                <div className="flex flex-wrap gap-1.5">
                  <span className="font-mono text-xs px-2 py-0.5 rounded-md bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[#ea580c] font-semibold">
                    {inspectingSkill.isSandboxed ? 'Isolated Subprocess' : 'Host Execution'}
                  </span>
                  <span className="font-mono text-xs px-2 py-0.5 rounded-md bg-[var(--bg-elevated)] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                    Risk: {inspectingSkill.riskLevel}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-3 border-t border-[var(--border-subtle)] shrink-0">
              <button
                type="button"
                onClick={() => setInspectingSkill(null)}
                className="px-4 py-1.5 rounded-lg bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)] text-[var(--text-primary)] border border-[var(--border-subtle)] text-xs font-semibold cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
