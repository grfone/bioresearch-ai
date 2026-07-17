// components/StatusBar.tsx
/**
 * StatusBar.tsx
 * --------------
 * Status bar component showing system state and workspace info.
 *
 * Displays current workspace status, paper count, and AI agent activity.
 * Can be placed at the top or bottom of the application shell.
 *
 * Uses CSS classes: .status-bar (we'll define a simple class) but we can
 * rely on existing utility classes and inline styles.
 *
 * @module components/StatusBar
 */

import React from 'react';
import { useWorkspaceStore } from '../workspaceStore';
import { Activity, Database, Cpu } from 'lucide-react';

interface StatusBarProps {
  /** Additional CSS classes */
  className?: string;
}

export const StatusBar: React.FC<StatusBarProps> = ({ className = '' }) => {
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);

  return (
    <div
      className={`flex items-center justify-between px-6 py-3 border-t border-border-default bg-background-secondary/50 text-xs text-muted ${className}`}
    >
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-primary" />
          <span>System: Operational</span>
        </div>
        {workspace && (
          <>
            <div className="flex items-center gap-2">
              <Database size={14} className="text-secondary" />
              <span>Papers: {workspace.total_papers}</span>
            </div>
            <div className="flex items-center gap-2">
              <Cpu size={14} className="text-secondary" />
              <span>Status: {workspace.status}</span>
            </div>
          </>
        )}
      </div>
      <div className="flex items-center gap-4">
        <span className="status-indicator status-idle">
          <span className="status-dot" />
          AI Ready
        </span>
        <span>{new Date().toLocaleTimeString()}</span>
      </div>
    </div>
  );
};