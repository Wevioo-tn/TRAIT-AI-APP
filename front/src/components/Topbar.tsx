import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { colors, fonts } from "../theme";

export default function Topbar({ pageTitle }: { pageTitle: string }) {
  const { username, logout } = useAuth();
  const navigate = useNavigate();
  const [profileOpen, setProfileOpen] = useState(false);

  function handleLogout() {
    setProfileOpen(false);
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <header
      className="tp-topbar tp-page-pad"
      style={{
        background: "#FFFFFF",
        borderBottom: `1px solid ${colors.border}`,
        padding: "12px 26px",
        display: "flex",
        alignItems: "center",
        gap: 22,
        position: "sticky",
        top: 0,
        zIndex: 20,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 5,
            background: colors.navy900,
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 12,
            fontWeight: 700,
          }}
        >
          SA
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: -0.1 }}>Contrôle des instruments de paiement</span>
          <span
            className="tp-topbar-sub"
            style={{ fontSize: 10.5, letterSpacing: 0.9, textTransform: "uppercase", color: colors.textMuted }}
          >
            Service achats · Factoring Tunis
          </span>
        </div>
      </div>

      <div className="tp-vdivider" style={{ width: 1, height: 30, background: colors.dividerTopbar }} />
      <div style={{ fontSize: 13, fontWeight: 600, color: colors.textHeading }}>{pageTitle}</div>

      <div className="tp-topbar-actions" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 14 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            background: colors.bgChip,
            border: `1px solid ${colors.borderInput}`,
            borderRadius: 5,
            padding: "6px 10px",
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: colors.green,
              animation: "pulse 1.8s infinite",
            }}
          />
          <span style={{ fontSize: 11.5, color: colors.textSecondary, fontWeight: 500 }}>Agent IA actif</span>
        </div>

        <div className="tp-vdivider" style={{ width: 1, height: 30, background: colors.dividerTopbar }} />

        <div style={{ position: "relative" }}>
          <div
            onClick={() => setProfileOpen((open) => !open)}
            style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}
          >
            <div
              style={{
                width: 29,
                height: 29,
                borderRadius: "50%",
                background: colors.blue700,
                color: "#fff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 11,
                fontWeight: 600,
              }}
            >
              {(username || "?").slice(0, 2).toUpperCase()}
            </div>
            <span style={{ fontSize: 12, fontWeight: 500 }}>{username || "Utilisateur"}</span>
            <span
              style={{
                fontSize: 9,
                color: "#9AA9B7",
                transition: "transform .15s",
                transform: `rotate(${profileOpen ? 180 : 0}deg)`,
              }}
            >
              ▾
            </span>
          </div>

          {profileOpen && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                position: "absolute",
                top: "100%",
                right: 0,
                marginTop: 8,
                minWidth: 168,
                background: "#fff",
                border: `1px solid ${colors.border}`,
                borderRadius: 6,
                boxShadow: "0 6px 22px rgba(11,34,57,.18)",
                overflow: "hidden",
                zIndex: 30,
              }}
            >
              <a
                onClick={handleLogout}
                title="Se déconnecter"
                style={{
                  display: "block",
                  padding: "9px 14px",
                  fontSize: 12,
                  color: colors.blue700,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  fontFamily: fonts.sans,
                }}
              >
                Déconnexion
              </a>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
