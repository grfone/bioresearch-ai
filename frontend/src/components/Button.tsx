/**
 * Button.tsx
 * ----------
 * Reusable button component with variants and loading state.
 *
 * Supports:
 * - Variants: primary, secondary, outline, ghost
 * - Loading state (disables button, shows spinner)
 * - Icons (left and right)
 * - Full width option
 *
 * Uses CSS classes from the design system:
 * - .btn, .btn-primary, .btn-secondary, .btn-outline, .btn-ghost
 *
 * @module components/Button
 */

import React from 'react';
import { LoadingSpinner } from './LoadingSpinner';

type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Button visual style */
  variant?: ButtonVariant;
  /** Whether the button is in a loading state */
  loading?: boolean;
  /** Icon to display on the left */
  leftIcon?: React.ReactNode;
  /** Icon to display on the right */
  rightIcon?: React.ReactNode;
  /** Whether the button should span full width */
  fullWidth?: boolean;
  /** Button content */
  children?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  loading = false,
  leftIcon,
  rightIcon,
  fullWidth = false,
  children,
  className = '',
  disabled,
  ...rest
}) => {
  const variantClass = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    outline: 'btn-outline',
    ghost: 'btn-ghost',
  }[variant];

  const widthClass = fullWidth ? 'w-full' : '';

  return (
    <button
      className={`btn ${variantClass} ${widthClass} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <LoadingSpinner size={18} />}
      {!loading && leftIcon}
      {children}
      {!loading && rightIcon}
    </button>
  );
};