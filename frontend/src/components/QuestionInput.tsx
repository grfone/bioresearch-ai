// components/QuestionInput.tsx
/**
 * QuestionInput.tsx
 * ------------------
 * Reusable input component for biomedical research questions.
 *
 * Used on the Home page and optionally within the Workspace to update the
 * research question. It provides a large, focused input with optional
 * submit button and loading state.
 *
 * @module components/QuestionInput
 */

import React, { useState } from 'react';

interface QuestionInputProps {
  /** Initial value */
  initialValue?: string;
  /** Placeholder text */
  placeholder?: string;
  /** Loading state */
  loading?: boolean;
  /** Callback when the question is submitted */
  onSubmit: (question: string) => void | Promise<void>;
  /** Additional CSS classes */
  className?: string;
  /** Auto-focus the input */
  autoFocus?: boolean;
}

export const QuestionInput: React.FC<QuestionInputProps> = ({
  initialValue = '',
  placeholder = 'Ask a biomedical research question…',
  loading = false,
  onSubmit,
  className = '',
  autoFocus = false,
}) => {
  const [question, setQuestion] = useState(initialValue);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim() && !loading) {
      onSubmit(question.trim());
    }
  };

  return (
    <form onSubmit={handleSubmit} className={`w-full ${className}`}>
      <div className="command-bar">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={placeholder}
          className="flex-1 bg-transparent border-none outline-none text-primary placeholder:text-muted text-lg"
          disabled={loading}
          autoFocus={autoFocus}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={loading || !question.trim()}
        >
          {loading ? 'Processing…' : 'Submit'}
        </button>
      </div>
    </form>
  );
};