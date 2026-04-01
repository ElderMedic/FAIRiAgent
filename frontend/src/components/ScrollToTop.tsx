import { useLayoutEffect } from 'react';
import { useLocation } from 'react-router-dom';

/** Scroll to top on client-side navigation (SPA default keeps scroll position). */
export default function ScrollToTop() {
  const { pathname } = useLocation();

  useLayoutEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
}
