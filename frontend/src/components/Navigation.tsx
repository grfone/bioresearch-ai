// components/Navigation.tsx
/**
 * Navigation.tsx
 * --------------
 * Sidebar navigation component for the BioResearch AI application.
 *
 * Displays the application logo and navigation links to main sections.
 * The active link is highlighted using the current route.
 *
 * Uses CSS classes from the design system:
 * - .sidebar, .sidebar-logo, .sidebar-title, .sidebar-subtitle
 * - .nav-list, .nav-item, .nav-item-active
 *
 * @module components/Navigation
 */

import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Home, FolderOpen, FileText, History, Settings, Sparkles } from 'lucide-react';

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
}

const navItems: NavItem[] = [
  { to: '/', label: 'Home', icon: <Home size={20} /> },
  { to: '/workspaces', label: 'Workspaces', icon: <FolderOpen size={20} /> },
  { to: '/reports', label: 'Reports', icon: <FileText size={20} /> },
  { to: '/history', label: 'History', icon: <History size={20} /> },
  { to: '/settings', label: 'Settings', icon: <Settings size={20} /> },
];

export const Navigation: React.FC = () => {
  const location = useLocation();

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    return location.pathname.startsWith(path);
  };

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">
          <Sparkles size={24} />
        </div>
        <div className="sidebar-logo-text">
          <span className="sidebar-title">BioResearch AI</span>
          <span className="sidebar-subtitle">Scientific Workstation</span>
        </div>
      </div>

      {/* Navigation List */}
      <nav className="nav-list">
        {navItems.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className={`nav-item ${isActive(item.to) ? 'nav-item-active' : ''}`}
          >
            {item.icon}
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>

      {/* Optional footer or user info */}
      <div className="mt-auto text-xs text-muted border-t border-border-subtle pt-4">
        <p>v0.1.0</p>
        <p className="mt-1">AI Research Assistant</p>
      </div>
    </aside>
  );
};