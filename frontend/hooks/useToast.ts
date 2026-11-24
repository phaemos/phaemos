'use client';

import { createContext, useContext, useReducer, useCallback } from 'react';

export type ToastType = 'success' | 'warning' | 'error' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

interface ToastState {
  toasts: Toast[];
}

type ToastAction =
  | { type: 'ADD'; toast: Toast }
  | { type: 'REMOVE'; id: string };

function reducer(state: ToastState, action: ToastAction): ToastState {
  switch (action.type) {
    case 'ADD':
      return { toasts: [...state.toasts, action.toast] };
    case 'REMOVE':
      return { toasts: state.toasts.filter((t) => t.id !== action.id) };
    default:
      return state;
  }
}

interface ToastContextValue {
  toasts: Toast[];
  addToast: (type: ToastType, message: string) => void;
  removeToast: (id: string) => void;
}

import React from 'react';

export const ToastContext = createContext<ToastContextValue>({
  toasts: [],
  addToast: () => {},
  removeToast: () => {},
});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, { toasts: [] });

  const removeToast = useCallback((id: string) => {
    dispatch({ type: 'REMOVE', id });
  }, []);

  const addToast = useCallback(
    (type: ToastType, message: string) => {
      const id = crypto.randomUUID();
      dispatch({ type: 'ADD', toast: { id, type, message } });
      // a success or an info note times out. An error or a warning stays until the reader dismisses it, because a
      // sentence that says what went wrong must not vanish before it is read.
      if (type === 'success' || type === 'info') setTimeout(() => removeToast(id), 6000);
    },
    [removeToast],
  );

  return React.createElement(
    ToastContext.Provider,
    { value: { toasts: state.toasts, addToast, removeToast } },
    children,
  );
}

export function useToast() {
  return useContext(ToastContext);
}
