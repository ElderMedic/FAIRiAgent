import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { withSessionRouteSearch } from '../utils/session';

export default function SessionRouteSync() {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const nextSearch = withSessionRouteSearch(location.search);
    if (nextSearch === location.search) {
      return;
    }
    navigate(
      {
        pathname: location.pathname,
        search: nextSearch,
      },
      {
        replace: true,
        state: location.state,
      },
    );
  }, [location.pathname, location.search, location.state, navigate]);

  return null;
}
