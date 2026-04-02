import { useEffect } from 'react';

const BASE = 'FAIRiAgent';

/**
 * Sets document.title for the current view. Pass a short page name (e.g. "Upload").
 */
export function usePageTitle(pageTitle: string) {
  useEffect(() => {
    const suffix = pageTitle.trim();
    document.title = suffix ? `${suffix} · ${BASE}` : BASE;
    return () => {
      document.title = BASE;
    };
  }, [pageTitle]);
}
