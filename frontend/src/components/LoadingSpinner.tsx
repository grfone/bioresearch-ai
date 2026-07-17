/**
 * LoadingSpinner.tsx
 * ------------------
 * Reusable loading spinner component.
 *
 * Uses the .spinner CSS class from the design system.
 *
 * @module components/LoadingSpinner
 */

import React from 'react';

interface LoadingSpinnerProps {
  /** Size of the spinner in pixels (width/height). Default: 28 */
  size?: number;
  /** Additional CSS classes */
  className?: string;
}

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({
  size = 28,
  className = '',
}) => {
  return (
    <div
      className={`spinner ${className}`}
      style={{ width: size, height: size }}
      role="status"
      aria-label="Loading"
    />
  );
};