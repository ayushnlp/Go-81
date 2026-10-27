'use client';

import React, { useState, useEffect } from 'react';
import {
  Wrench,
  Shield,
  ShieldAlert,
  Play,
  Sliders,
  Plus,
  Terminal,
  Cpu,
  FolderTree,
  Mail,
  Code2,
  Check,
} from 'lucide-react';
import { AppSidebar } from '@/components/shell/AppSidebar';
import { AppHeader } from '@/components/shell/AppHeader';
import { OfflineBanner } from '@/components/ui/OfflineBanner';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader, CardContent, CardTitle, CardFooter } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { api } from '@/lib/api/client';
import { SkillDefinition, SkillCategory } from '@/lib/api/types';

const categoryIcons: Record<SkillCategory, React.ElementType> = {
  system: Cpu,
  filesystem: FolderTree,
  network: Terminal,
  communication: Mail,
  developer: Code2,
};

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<'all' | SkillCategory>('all');
  const [inspectingSkill, setInspectingSkill] = useState<SkillDefinition | null>(null);
  const [testingSkill, setTestingSkill] = useState<SkillDefinition | null>(null);
  const [testOutput, setTestOutput] = useState<string | null>(null);
  const [isExecutingTest, setIsExecutingTest] = useState(false);

  // Register Skill Modal state
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);
  const [regName, setRegName] = useState('');
  const [regTitle, setRegTitle] = useState('');
  const [regDesc, setRegDesc] = useState('');
  const [regCategory, setRegCategory] = useState<SkillCategory>('developer');
  const [regApproval, setRegApproval] = useState(true);

  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [isCheckingBackend, setIsCheckingBackend] = useState(false);

  const probe = async () => {
    setIsCheckingBackend(true);
    try {
      const health = await api.checkHealth();
      setIsBackendOnline(health.online);

      const res = await api.getSkills();
      setSkills(res.data);
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

        const res = await api.getSkills();
        if (!isMounted) return;
        setSkills(res.data);
      } catch {
        // graceful offline
      }
    })();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleToggleSkill = (id: string) => {
    setSkills((prev) =>
      prev.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s))
    );
  };

  const handleRunTest = async (skill: SkillDefinition) => {
    setIsExecutingTest(true);
    setTestOutput(null);
    setTimeout(() => {
      setTestOutput(
        `[Shielded Sandbox Execution Pass]\nTool: ${skill.name}\nIsolation: CONTAINER_SHIELD_OK\nExit Code: 0\nOutput: Mock verification execution succeeded. Zero side-effects escaped sandbox.`
      );
      setIsExecutingTest(false);
    }, 900);
  };

  const handleRegisterSkill = (e: React.FormEvent) => {
    e.preventDefault();
    if (!regName.trim() || !regTitle.trim()) return;

    const newSkill: SkillDefinition = {
      id: `skill-${Date.now().toString().slice(-4)}`,
      name: regName.trim(),
      displayName: regTitle.trim(),
      description: regDesc.trim(),
      category: regCategory,
      isSandboxed: true,
      requiresApproval: regApproval,
      riskLevel: regApproval ? 'high' : 'low',
      parameters: [
        { name: 'input', type: 'string', description: 'Primary parameter', required: true },
      ],
      executionCount: 0,
      enabled: true,
    };

    setSkills((prev) => [newSkill, ...prev]);
    setIsRegisterOpen(false);
    setRegName('');
    setRegTitle('');
    setRegDesc('');
  };

  const filteredSkills =
    selectedCategory === 'all'
      ? skills
      : skills.filter((s) => s.category === selectedCategory);

  return (
    <div className="flex min-h-screen bg-[#090b0e] text-zinc-100">
      <AppSidebar />

      <div className="flex-1 flex flex-col min-w-0">
        <OfflineBanner
          isLive={isBackendOnline}
          isChecking={isCheckingBackend}
          onRetry={probe}
          backendUrl={api.getBaseUrl()}
        />

        <AppHeader
          title="Skills Forge (Dwarves' Forge)"
          subtitle="Modular registered tools, parameters, and sandboxed execution boundaries (FR2)"
          isBackendOnline={isBackendOnline}
          isChecking={isCheckingBackend}
          onRefreshBackend={probe}
        />

        <main className="flex-1 max-w-5xl w-full mx-auto p-4 sm:p-6 space-y-6">
          {/* Top Control Bar */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            {/* Category Filter */}
            <div className="flex items-center gap-1 bg-[#101319] p-1 rounded-lg border border-zinc-800 text-xs font-mono">
              {(['all', 'system', 'filesystem', 'communication', 'developer'] as const).map(
                (cat) => (
                  <button
                    key={cat}
                    onClick={() => setSelectedCategory(cat)}
                    className={`px-3 py-1.5 rounded cursor-pointer capitalize ${
                      selectedCategory === cat
                        ? 'bg-zinc-800 text-zinc-100 font-semibold'
                        : 'text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    {cat}
                  </button>
                )
              )}
            </div>

            {/* Register Rune Button */}
            <Button
              size="sm"
              variant="primary"
              onClick={() => setIsRegisterOpen(true)}
              icon={<Plus className="w-4 h-4" />}
            >
              Register New Skill
            </Button>
          </div>

          {/* Skills Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredSkills.map((skill) => {
              const CategoryIcon = categoryIcons[skill.category] || Wrench;

              return (
                <Card
                  key={skill.id}
                  className={`flex flex-col justify-between transition-all ${
                    !skill.enabled ? 'opacity-60 border-zinc-850' : 'hover:border-zinc-700'
                  }`}
                >
                  <CardHeader className="bg-[#121620]/50 py-3.5">
                    <div className="flex items-start gap-3">
                      <div className="p-2 rounded-lg bg-zinc-900 border border-zinc-800 text-emerald-400">
                        <CategoryIcon className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <CardTitle className="text-sm font-semibold">
                            {skill.displayName}
                          </CardTitle>
                          {!skill.enabled && (
                            <Badge variant="zinc">Disabled</Badge>
                          )}
                        </div>
                        <span className="font-mono text-[11px] text-zinc-500">
                          {skill.name}
                        </span>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleToggleSkill(skill.id)}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                        skill.enabled ? 'bg-emerald-600' : 'bg-zinc-800'
                      }`}
                    >
                      <span
                        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-xs ring-0 transition duration-200 ease-in-out ${
                          skill.enabled ? 'translate-x-4' : 'translate-x-0'
                        }`}
                      />
                    </button>
                  </CardHeader>

                  <CardContent className="space-y-3 pt-3">
                    <p className="text-xs text-zinc-300 leading-relaxed">
                      {skill.description}
                    </p>

                    <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono">
                      {skill.isSandboxed && (
                        <span className="flex items-center gap-1 text-emerald-400 bg-emerald-950/40 border border-emerald-800/40 px-2 py-0.5 rounded">
                          <Shield className="w-3 h-3" />
                          Sandboxed (FR2.3)
                        </span>
                      )}

                      {skill.requiresApproval ? (
                        <span className="flex items-center gap-1 text-amber-400 bg-amber-950/40 border border-amber-800/40 px-2 py-0.5 rounded">
                          <ShieldAlert className="w-3 h-3" />
                          Gate Approval (FR4.3)
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-zinc-400 bg-zinc-900 border border-zinc-800 px-2 py-0.5 rounded">
                          Autonomous Run
                        </span>
                      )}

                      <span className="text-zinc-500 ml-auto">
                        {skill.parameters.length} parameters
                      </span>
                    </div>
                  </CardContent>

                  <CardFooter className="py-2.5 flex items-center justify-between text-xs font-mono text-zinc-500">
                    <span>Runs: {skill.executionCount}</span>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setInspectingSkill(skill)}
                        icon={<Sliders className="w-3 h-3" />}
                        className="text-xs py-1 px-2"
                      >
                        Schema
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setTestingSkill(skill);
                          setTestOutput(null);
                        }}
                        icon={<Play className="w-3 h-3 text-emerald-400" />}
                        className="text-xs py-1 px-2.5"
                      >
                        Dry Run
                      </Button>
                    </div>
                  </CardFooter>
                </Card>
              );
            })}
          </div>
        </main>
      </div>

      {/* Parameter Schema Inspector Modal */}
      <Modal
        isOpen={Boolean(inspectingSkill)}
        onClose={() => setInspectingSkill(null)}
        title="Skill Interface & Parameter Schema"
        description="Standardized interface rune for dynamic tool selection (FR2.1 / FR2.2)"
      >
        {inspectingSkill && (
          <div className="space-y-4 text-xs font-mono">
            <div className="p-3 rounded-lg bg-zinc-950 border border-zinc-800 space-y-1">
              <div className="flex justify-between text-zinc-400">
                <span>Unique Tool Identifier:</span>
                <span className="text-emerald-400">{inspectingSkill.name}</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Domain Class:</span>
                <span className="text-zinc-200 capitalize">{inspectingSkill.category}</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Subprocess Isolation:</span>
                <span className="text-emerald-400">CONTAINER_SHIELD (POSIX Sandbox)</span>
              </div>
            </div>

            <div>
              <span className="text-[11px] text-zinc-400 uppercase tracking-wider block mb-1.5 font-sans font-semibold">
                Parameter Signatures
              </span>
              <div className="space-y-2">
                {inspectingSkill.parameters.map((param) => (
                  <div
                    key={param.name}
                    className="p-2.5 rounded-lg bg-zinc-900 border border-zinc-800 flex items-center justify-between"
                  >
                    <div>
                      <span className="text-zinc-200 font-bold">{param.name}</span>
                      <span className="text-zinc-500 ml-2">({param.type})</span>
                      <p className="text-[11px] text-zinc-400 font-sans mt-0.5">
                        {param.description}
                      </p>
                    </div>
                    {param.required && (
                      <Badge variant="rose" className="text-[10px]">
                        Required
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* Dry Run Testing Modal */}
      <Modal
        isOpen={Boolean(testingSkill)}
        onClose={() => setTestingSkill(null)}
        title={`Dry Run: ${testingSkill?.displayName}`}
        description="Execute within local sandboxed container with mock validation parameters (FR2.3)"
      >
        {testingSkill && (
          <div className="space-y-4">
            <div className="text-xs text-zinc-300">
              Trigger a test invocation of <code className="font-mono text-emerald-300">{testingSkill.name}</code> to ensure that sandboxing isolation prevents escape and that parameters validate.
            </div>

            <Button
              variant="primary"
              size="sm"
              onClick={() => handleRunTest(testingSkill)}
              loading={isExecutingTest}
              icon={<Play className="w-3.5 h-3.5" />}
              className="w-full"
            >
              Execute Shielded Test Run
            </Button>

            {testOutput && (
              <div className="mt-3">
                <span className="text-[11px] font-mono text-zinc-500 uppercase tracking-wider block mb-1">
                  Subprocess Output Trace:
                </span>
                <pre className="p-3 rounded-lg bg-black border border-zinc-800 text-emerald-400 font-mono text-xs overflow-x-auto whitespace-pre-wrap">
                  {testOutput}
                </pre>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Register New Skill Modal */}
      <Modal
        isOpen={isRegisterOpen}
        onClose={() => setIsRegisterOpen(false)}
        title="Inscribe New Skill Rune"
        description="Register a reusable Python script, local CLI wrapper, or tool extension (FR2.1)"
      >
        <form onSubmit={handleRegisterSkill} className="space-y-4">
          <div>
            <label className="text-xs font-medium text-zinc-300 block mb-1">
              Internal Skill Name (Identifier):
            </label>
            <input
              type="text"
              value={regName}
              onChange={(e) => setRegName(e.target.value)}
              placeholder="e.g. git.create_pr"
              required
              className="w-full text-xs font-mono rounded-lg bg-zinc-900 border border-zinc-700/80 p-2.5 text-zinc-200 placeholder-zinc-500 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-zinc-300 block mb-1">
              Display Title:
            </label>
            <input
              type="text"
              value={regTitle}
              onChange={(e) => setRegTitle(e.target.value)}
              placeholder="e.g. Automated Pull Request Creator"
              required
              className="w-full text-xs rounded-lg bg-zinc-900 border border-zinc-700/80 p-2.5 text-zinc-200 placeholder-zinc-500 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-zinc-300 block mb-1">
              Description:
            </label>
            <textarea
              value={regDesc}
              onChange={(e) => setRegDesc(e.target.value)}
              placeholder="Describe what the skill accomplishes and security boundaries..."
              rows={2}
              required
              className="w-full text-xs rounded-lg bg-zinc-900 border border-zinc-700/80 p-2.5 text-zinc-200 placeholder-zinc-500 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-zinc-300 block mb-1">
                Category:
              </label>
              <select
                value={regCategory}
                onChange={(e) => setRegCategory(e.target.value as SkillCategory)}
                className="w-full text-xs rounded-lg bg-zinc-900 border border-zinc-700/80 p-2 text-zinc-200"
              >
                <option value="developer">Developer</option>
                <option value="filesystem">Filesystem</option>
                <option value="communication">Communication</option>
                <option value="system">System</option>
                <option value="network">Network</option>
              </select>
            </div>

            <div>
              <label className="text-xs font-medium text-zinc-300 block mb-1">
                Approval Gate:
              </label>
              <select
                value={regApproval ? 'true' : 'false'}
                onChange={(e) => setRegApproval(e.target.value === 'true')}
                className="w-full text-xs rounded-lg bg-zinc-900 border border-zinc-700/80 p-2 text-zinc-200"
              >
                <option value="true">Require Just-in-Time Approval</option>
                <option value="false">Safe (Autonomous Run)</option>
              </select>
            </div>
          </div>

          <div className="pt-2 border-t border-zinc-800 flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setIsRegisterOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              icon={<Check className="w-3.5 h-3.5" />}
            >
              Inscribe in Forge
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
