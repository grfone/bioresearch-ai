/**
 * ToastContainer.tsx
 * ------------------
 * Renders a list of toast notifications.
 *
 * Positioned at the bottom-right corner of the screen.
 * Each toast auto-dismisses after its duration.
 *
 * Uses CSS classes from the design system:
 * - .toast, .toast-success, .toast-warning, .toast-info, .toast-error
 *
 * @module components/ToastContainer
 */

import React from 'react';
import { useToastStore } from '../state/toastStore';
import { X } from 'lucide-react';

const toastTypeStyles = {
  info: 'toast-info border-l-4 border-primary',
  success: 'toast-success border-l-4 border-success',
  warning: 'toast-warning border-l-4 border-warning',
  error: 'toast-error border-l-4 border-error',
};

export const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToastStore();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-6 right-6 z-toast flex flex-col gap-3 max-w-sm w-full pointer-events-none">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast pointer-events-auto animate-fade-up ${toastTypeStyles[toast.type]}`}
          role="alert"
        >
          <span className="flex-1 text-sm">{toast.message}</span>
          <button
            onClick={() => removeToast(toast.id)}
            className="text-muted hover:text-primary transition-colors"
            aria-label="Dismiss notification"
          >
            <X size={16} />
          </button>
        </div>
      ))}
    </div>
  );
};