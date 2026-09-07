import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { colors } from "../theme";

type ToastKind = "ok" | "ko";
interface ToastState {
  kind: ToastKind;
  titre: string;
  detail: string;
}

interface ToastApi {
  show: (kind: ToastKind, titre: string, detail: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const show = useCallback((kind: ToastKind, titre: string, detail: string) => {
    clearTimeout(timeoutRef.current);
    setToast({ kind, titre, detail });
    timeoutRef.current = setTimeout(() => setToast(null), 4200);
  }, []);

  const okStyle = { background: colors.greenBg, border: `1px solid ${colors.greenBorder}`, color: colors.greenText };
  const koStyle = { background: colors.redBg, border: `1px solid ${colors.redBorder}`, color: colors.redText };

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {toast && (
        <div
          className="tp-toast"
          style={{
            position: "fixed",
            right: 22,
            bottom: 22,
            zIndex: 60,
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            minWidth: 300,
            maxWidth: 420,
            padding: "12px 14px",
            borderRadius: 6,
            boxShadow: "0 6px 22px rgba(11,34,57,.18)",
            ...(toast.kind === "ok" ? okStyle : koStyle),
          }}
        >
          <span style={{ fontSize: 13, lineHeight: 1.2 }}>{toast.kind === "ok" ? "✓" : "⚠"}</span>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>{toast.titre}</span>
            <span style={{ fontSize: 11.5, lineHeight: 1.45 }}>{toast.detail}</span>
          </div>
          <span
            onClick={() => {
              clearTimeout(timeoutRef.current);
              setToast(null);
            }}
            style={{ marginLeft: "auto", fontSize: 13, cursor: "pointer", opacity: 0.6 }}
          >
            ×
          </span>
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside a ToastProvider");
  return context;
}
