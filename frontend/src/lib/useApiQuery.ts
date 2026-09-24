import { useCallback, useEffect, useState } from 'react';

import type { ApiError, ApiResult } from './api';

export type QueryState<T> =
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: ApiError };

/** Shared loading/success/error state machine for a single GET-style
 * request — every page that calls the BFF/Django uses this instead of
 * re-implementing its own ad-hoc useState/useEffect loading logic. */
export function useApiQuery<T>(fetcher: () => Promise<ApiResult<T>>, deps: unknown[]): QueryState<T> & { refetch: () => void } {
  const [state, setState] = useState<QueryState<T>>({ status: 'loading' });
  const [reloadToken, setReloadToken] = useState(0);

  const refetch = useCallback(() => setReloadToken((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    fetcher().then((result) => {
      if (cancelled) return;
      setState(result.ok ? { status: 'success', data: result.data } : { status: 'error', error: result.error });
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken]);

  return { ...state, refetch };
}
