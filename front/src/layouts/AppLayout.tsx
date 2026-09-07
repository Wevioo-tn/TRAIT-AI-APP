import { Outlet, useLocation } from "react-router-dom";

import Topbar from "../components/Topbar";
import { colors } from "../theme";

function pageTitleFor(pathname: string): string {
  if (pathname.startsWith("/traites/")) return "Analyse OCR / NLP";
  return "Traites à contrôler";
}

export default function AppLayout() {
  const location = useLocation();

  return (
    <div style={{ display: "flex", minHeight: "100vh", alignItems: "stretch", background: colors.bgPage }}>
      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <Topbar pageTitle={pageTitleFor(location.pathname)} />
        <Outlet />
      </main>
    </div>
  );
}
