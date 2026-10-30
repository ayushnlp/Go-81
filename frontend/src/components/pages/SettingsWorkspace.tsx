'use client';

import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  Cpu,
  Save,
  CheckCircle2,
  Server,
  Database,
  RefreshCw,
  Sun,
  Moon,
  Laptop,
  Lock,
} from 'lucide-react';
import { api } from '@/lib/api/client';
import { AppearancePreset, AudienceMode, PrivacySettings } from '@/lib/api/types';
import { DEMO_PRIVACY_SETTINGS } from '@/lib/api/fixtures';

interface SettingsWorkspaceProps {
  currentTheme: AppearancePreset;
  onThemeChange: (theme: AppearancePreset) => void;
  currentMode: AudienceMode;
  onModeChange: (mode: AudienceMode) => void;
}

export const SettingsWorkspace: React.FC<SettingsWorkspaceProps> = ({
  currentTheme,
  onThemeChange,
  currentMode,
  onModeChange,
}) => {
  const [settings, setSettings] = useState<PrivacySettings>(DEMO_PRIVACY_SETTINGS);
  const [isSaved, setIsSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isBackendOnline, setIsBackendOnline] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const health = await api.checkHealth();
        setIsBackendOnline(health.online);
        const res = await api.getPrivacySettings();
        if (res.data) setSettings(res.data);
      } catch {
        // offline fallback
      }
    })();
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await api.updatePrivacySettings(settings);
      setIsSaved(true);
      setTimeout(() => setIsSaved(false), 2500);
    } catch {
      // offline
    } finally {
      setIsSaving(false);
    }
  };

  const themes: { id: AppearancePreset; label: string; icon: React.ElementType; description: string }[] = [
    { id: 'dark', label: 'Dark Charcoal', icon: Moon, description: 'Default deep charcoal command center theme' },
    { id: 'light', label: 'Warm Light', icon: Sun, description: 'Warm-white minimal light theme with high contrast' },
    { id: 'oled-dark', label: 'OLED Pure Black', icon: Moon, description: 'True pitch-black palette optimized for OLED displays' },
    { id: 'oled-light', label: 'Crisp White', icon: Sun, description: 'Pure white high-luminance theme' },
  ];

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto p-6 md:p-8 bg-[var(--bg-canvas)]">
      <div className="max-w-4xl w-full mx-auto space-y-6">
        {/* Section 1: Appearance & Theme */}
        <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Appearance & Theme
            </h3>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Select your preferred visual style across all pages and workspaces
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            {themes.map((t) => {
              const Icon = t.icon;
              const isSelected = currentTheme === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => onThemeChange(t.id)}
                  className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer flex items-start space-x-3 ${
                    isSelected
                      ? 'border-[#ea580c] bg-[var(--accent-primary-bg)] shadow-xs'
                      : 'border-[var(--border-subtle)] bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)]'
                  }`}
                >
                  <div className={`p-2 rounded-lg shrink-0 ${isSelected ? 'bg-[#ea580c] text-white' : 'bg-[var(--bg-surface)] text-[var(--text-secondary)]'}`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <div>
                    <span className={`text-xs font-semibold block ${isSelected ? 'text-[#ea580c]' : 'text-[var(--text-primary)]'}`}>
                      {t.label}
                    </span>
                    <span className="text-[11px] text-[var(--text-muted)] mt-0.5 block leading-relaxed">
                      {t.description}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Section 2: Audience Mode */}
        <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Audience Mode
            </h3>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Customize interface density and diagnostics display
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <button
              type="button"
              onClick={() => onModeChange('user')}
              className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer flex items-start space-x-3 ${
                currentMode === 'user'
                  ? 'border-[#ea580c] bg-[var(--accent-primary-bg)] shadow-xs'
                  : 'border-[var(--border-subtle)] bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)]'
              }`}
            >
              <div className={`p-2 rounded-lg shrink-0 ${currentMode === 'user' ? 'bg-[#ea580c] text-white' : 'bg-[var(--bg-surface)] text-[var(--text-secondary)]'}`}>
                <Laptop className="w-4 h-4" />
              </div>
              <div>
                <span className={`text-xs font-semibold block ${currentMode === 'user' ? 'text-[#ea580c]' : 'text-[var(--text-primary)]'}`}>
                  User Mode
                </span>
                <span className="text-[11px] text-[var(--text-muted)] mt-0.5 block leading-relaxed">
                  Clean conversational experience with simplified action outcomes.
                </span>
              </div>
            </button>

            <button
              type="button"
              onClick={() => onModeChange('developer')}
              className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer flex items-start space-x-3 ${
                currentMode === 'developer'
                  ? 'border-[#ea580c] bg-[var(--accent-primary-bg)] shadow-xs'
                  : 'border-[var(--border-subtle)] bg-[var(--bg-elevated)] hover:bg-[var(--bg-subtle)]'
              }`}
            >
              <div className={`p-2 rounded-lg shrink-0 ${currentMode === 'developer' ? 'bg-[#ea580c] text-white' : 'bg-[var(--bg-surface)] text-[var(--text-secondary)]'}`}>
                <Cpu className="w-4 h-4" />
              </div>
              <div>
                <span className={`text-xs font-semibold block ${currentMode === 'developer' ? 'text-[#ea580c]' : 'text-[var(--text-primary)]'}`}>
                  Developer Mode
                </span>
                <span className="text-[11px] text-[var(--text-muted)] mt-0.5 block leading-relaxed">
                  Deep diagnostic telemetry, reasoning traces, and audit token inspectors.
                </span>
              </div>
            </button>
          </div>
        </div>

        {/* Section 3: Sovereign Security & Telemetry Policy */}
        <div className="p-5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-xs space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Local-First Sovereign Policy
            </h3>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Strict boundaries enforced by Go 81 sovereign runtime
            </p>
          </div>

          <div className="space-y-3 pt-1 text-xs">
            <div className="p-3.5 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <ShieldCheck className="w-4 h-4 text-emerald-500" />
                <div>
                  <span className="font-semibold text-[var(--text-primary)] block">Zero Outbound Telemetry</span>
                  <span className="text-[11px] text-[var(--text-muted)]">No model prompts or project data leave this device</span>
                </div>
              </div>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500">
                ENFORCED
              </span>
            </div>

            <div className="p-3.5 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <Lock className="w-4 h-4 text-emerald-500" />
                <div>
                  <span className="font-semibold text-[var(--text-primary)] block">AES-256-GCM Vault Encryption</span>
                  <span className="text-[11px] text-[var(--text-muted)]">Persistent memory and checkpoints encrypted at rest</span>
                </div>
              </div>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500">
                ACTIVE
              </span>
            </div>
          </div>
        </div>

        {/* Bottom Save Action */}
        <div className="flex justify-end pt-2">
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center space-x-2 px-5 py-2 rounded-xl bg-[#ea580c] hover:bg-[#c2410c] text-white text-xs font-semibold shadow-xs transition-colors cursor-pointer disabled:opacity-50"
          >
            {isSaving ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : isSaved ? (
              <CheckCircle2 className="w-4 h-4" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            <span>{isSaved ? 'Preferences Saved' : 'Save Preferences'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};

