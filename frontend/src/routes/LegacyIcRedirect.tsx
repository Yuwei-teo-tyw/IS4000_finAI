import { Navigate, useLocation } from "react-router-dom";

/** The Portfolio Manager role was the Investment Counsellor (/ic); old links and bookmarks land on /pm. */
export default function LegacyIcRedirect() {
  const { pathname, search } = useLocation();
  return <Navigate to={pathname.replace(/^\/ic(?=\/|$)/, "/pm") + search} replace />;
}
