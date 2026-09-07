import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/ToastProvider";
import { colors, fonts } from "../theme";

const inputStyle: React.CSSProperties = {
  border: `1px solid ${colors.borderInput}`,
  borderRadius: 5,
  padding: "9px 11px",
  fontFamily: fonts.mono,
  fontSize: 12.5,
  color: colors.textPrimary,
  outline: "none",
};

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const { login } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password.trim()) {
      toast.show("ko", "Connexion refusée", "Identifiant et mot de passe sont obligatoires.");
      return;
    }
    const ok = await login(username, password);
    if (!ok) {
      toast.show("ko", "Connexion refusée", "Identifiant ou mot de passe incorrect.");
      return;
    }
    toast.show("ok", `Bienvenue, ${username.trim()}`, "Session ouverte. Toutes vos actions sont tracées.");
    navigate("/", { replace: true });
  }

  return (
    <div className="tp-login-shell" style={{ display: "flex", minHeight: "100vh" }}>
      <div
        className="tp-login-brand"
        style={{
          width: "44%",
          minWidth: 320,
          background: colors.navy900,
          color: "#C9D6E4",
          padding: "48px 56px",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 6,
              background: colors.blue700,
              color: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 13,
              fontWeight: 700,
            }}
          >
            SA
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: "#fff" }}>Contrôle des instruments de paiement</span>
            <span style={{ fontSize: 10.5, letterSpacing: 0.9, textTransform: "uppercase", color: "#7C93AB" }}>
              Service achats · Factoring Tunis
            </span>
          </div>
        </div>

        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 18, maxWidth: 420 }}>
          <span style={{ fontSize: 26, lineHeight: 1.3, color: "#fff", fontWeight: 600, letterSpacing: -0.3 }}>
            Le contrôle des traites en 24 heures, sans céder sur la vigilance.
          </span>
          <span style={{ fontSize: 13, lineHeight: 1.65, color: "#9FB3C8" }}>
            L'agent extrait les champs du recto, rapproche le référentiel IMX et contrôle les mentions obligatoires.
            Signatures, cachets et endossement restent statués par le caissier.
          </span>
        </div>

        <div
          className="tp-login-stats"
          style={{ marginTop: "auto", display: "flex", gap: 28, paddingTop: 36, borderTop: "1px solid #1B3550" }}
        >
          {[
            ["27 000", "IP traités en 2025"],
            ["24 h", "délai cible par remise"],
            ["4", "zones sous contrôle humain"],
          ].map(([value, label]) => (
            <div key={label} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontFamily: fonts.mono, fontSize: 19, fontWeight: 600, color: "#fff" }}>{value}</span>
              <span style={{ fontSize: 11, color: "#7C93AB" }}>{label}</span>
            </div>
          ))}
        </div>
      </div>

      <div
        className="tp-login-formwrap"
        style={{
          flex: 1,
          minWidth: 280,
          background: colors.bgPage,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 40,
        }}
      >
        <form
          onSubmit={handleSubmit}
          style={{
            width: "100%",
            maxWidth: 392,
            background: colors.bgCard,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            padding: "28px 28px 24px",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 17, fontWeight: 600, letterSpacing: -0.1 }}>Connexion</span>
            <span style={{ fontSize: 12, color: colors.textMuted }}>Authentification par annuaire interne TLF</span>
          </div>

          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.7, color: colors.textMuted }}>
              Identifiant
            </span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="h.mansouri"
              style={inputStyle}
            />
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.7, color: colors.textMuted }}>
              Mot de passe
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={inputStyle}
            />
          </label>

          <button
            type="submit"
            style={{
              background: colors.navy900,
              color: "#fff",
              border: "none",
              borderRadius: 5,
              padding: "11px 14px",
              fontSize: 12.5,
              fontWeight: 600,
              fontFamily: "inherit",
              cursor: "pointer",
              marginTop: 2,
            }}
          >
            Se connecter
          </button>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              paddingTop: 12,
              borderTop: `1px solid ${colors.dividerLight}`,
            }}
          >
            <span style={{ fontSize: 11, color: colors.textMuted, lineHeight: 1.5 }}>
              Accès réservé aux collaborateurs habilités du service achats. Toute action est horodatée et tracée.
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}
