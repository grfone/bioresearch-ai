// layouts/MainLayout.tsx
/**
 * MainLayout.tsx
 * --------------
 * Primary application layout with sidebar navigation and content area.
 *
 * This layout provides the persistent application shell used throughout
 * BioResearch AI. It includes:
 *
 * - Sidebar navigation (optional)
 * - Header with title and actions (optional)
 * - Main content area
 * - Status bar (optional)
 *
 * The layout is flexible: it can be used with or without sidebar,
 * with or without a header, and with or without a status bar.
 *
 * Uses CSS classes from the design system:
 * - .app-shell, .sidebar, .main-content, .workspace-header, etc.
 *
 * @module layouts/MainLayout
 */

import React, { ReactNode } from 'react';
import { Navigation } from '../components/Navigation';
import { StatusBar } from '../components/StatusBar';

interface MainLayoutProps {
  /** Main content to render inside the layout */
  children: ReactNode;
  /** Whether to show the sidebar. Default: true */
  showSidebar?: boolean;
  /** Header title text */
  headerTitle?: string;
  /** Header subtitle text */
  headerSubtitle?: string;
  /** Additional elements to render in the header (right side) */
  headerActions?: ReactNode;
  /** Whether to show the status bar at the bottom. Default: true */
  showStatusBar?: boolean;
  /** Additional CSS classes for the content area */
  className?: string;
}

export const MainLayout: React.FC<MainLayoutProps> = ({
  children,
  showSidebar = true,
  headerTitle,
  headerSubtitle,
  headerActions,
  showStatusBar = true,
  className = '',
}) => {
  return (
    <div className="app-shell">
      {/* Sidebar */}
      {showSidebar && <Navigation />}

      {/* Main content area */}
      <div className="main-content">
        {/* Header */}
        {(headerTitle || headerSubtitle || headerActions) && (
          <header className="workspace-header">
            <div>
              {headerTitle && (
                <h1 className="workspace-title">{headerTitle}</h1>
              )}
              {headerSubtitle && (
                <p className="workspace-subtitle">{headerSubtitle}</p>
              )}
            </div>
            {headerActions && (
              <div className="header-actions">{headerActions}</div>
            )}
          </header>
        )}

        {/* Content */}
        <main className={`flex-1 ${className}`}>{children}</main>

        {/* Status Bar */}
        {showStatusBar && <StatusBar />}
      </div>
    </div>
  );
};