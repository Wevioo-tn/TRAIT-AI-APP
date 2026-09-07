import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { TraiteStatut } from "../api/types";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../components/ToastProvider";
import { computeSla, formatDate, formatDateTime, formatMontant } from "../lib/format";
import { colors, fonts } from "../theme";

const ALL_STATUSES: TraiteStatut[] = [
  "À traiter",
  "En cours OCR",
  "Écarts à traiter",
  "Contrôle manuel requis",
  "Renvoyée",
  "Fraude signalée",
  "Validée",
];
const COUNTER_STATUSES: TraiteStatut[] = [
  "À traiter",
  "En cours OCR",
  "Écarts à traiter",
  "Contrôle manuel requis",
  "Validée",
];
const COUNTER_ACCENTS: Record<string, string> = {
  "À traiter": colors.textMuted,
  "En cours OCR": colors.blue700,
  "Écarts à traiter": colors.orange,
  "Contrôle manuel requis": colors.purple,
  "Validée": colors.green,
};
const PER_PAGE = 6;

type Filter = TraiteStatut | "Toutes";

export default function QueuePage() {
  const [filter, setFilter] = useState<Filter>("Toutes");
  const [page, setPage] = useState(1);
  const [rectoFile, setRectoFile] = useState<File | null>(null);
  const [versoFile, setVersoFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState<"recto" | "verso" | null>(null);
  const rectoInputRef = useRef<HTMLInputElement>(null);
  const versoInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ["traites", filter, page],
    queryFn: () => api.listTraites({ statut: filter === "Toutes" ? undefined : filter, page, per_page: PER_PAGE }),
  });

  const countsQuery = useQuery({ queryKey: ["traites", "counts"], queryFn: api.getTraiteCounts });

  const launchMutation = useMutation({
    mutationFn: async () => {
      if (!rectoFile || !versoFile) throw new ApiError(422, "Le recto et le verso sont obligatoires.");
      const traite = await api.createTraite({});
      await api.uploadDocument(traite.id, "recto", rectoFile);
      await api.uploadDocument(traite.id, "verso", versoFile);
      await api.lancerAnalyse(traite.id);
      return traite;
    },
    onSuccess: (traite) => {
      toast.show("ok", "Analyse lancée", `La traite ${traite.numero_lcn} est en cours d'analyse.`);
      setRectoFile(null);
      setVersoFile(null);
      queryClient.invalidateQueries({ queryKey: ["traites"] });
      navigate(`/traites/${traite.id}`);
    },
    onError: (error: unknown) => {
      const message = error instanceof ApiError ? error.message : "Une erreur est survenue.";
      toast.show("ko", "Analyse impossible", message);
    },
  });

  const canStart = !!rectoFile && !!versoFile;

  const uploadNote =
    !rectoFile && !versoFile
      ? "Les deux faces sont obligatoires : le recto porte les champs extraits par OCR, le verso la zone d'endossement à l'ordre de SPG."
      : !rectoFile
        ? "Verso importé. Le recto reste obligatoire : sans lui aucun champ ne peut être extrait."
        : !versoFile
          ? "Recto importé. Le verso reste obligatoire pour contrôler l'endossement."
          : "Recto et verso prêts. L'agent extrait les 10 zones, rapproche le référentiel IMX et contrôle les mentions obligatoires.";

  function handleFile(kind: "recto" | "verso", file: File | undefined | null) {
    if (!file) return;
    if (kind === "recto") setRectoFile(file);
    else setVersoFile(file);
    toast.show(
      "ok",
      `${kind === "recto" ? "Recto" : "Verso"} importé — ${file.name}`,
      "Fichier prêt à être envoyé au lancement de l'analyse.",
    );
  }

  function renderDropzone(kind: "recto" | "verso") {
    const file = kind === "recto" ? rectoFile : versoFile;
    const inputRef = kind === "recto" ? rectoInputRef : versoInputRef;
    const active = dragOver === kind;

    return (
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(kind);
        }}
        onDragLeave={() => setDragOver(null)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(null);
          handleFile(kind, e.dataTransfer.files?.[0]);
        }}
        style={{
          position: "relative",
          flex: 1,
          minHeight: 132,
          borderRadius: 5,
          padding: 12,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 5,
          textAlign: "center",
          cursor: "pointer",
          overflow: "hidden",
          border: `1.5px dashed ${active ? colors.blue700 : file ? colors.greenBorder : "#C3CDD8"}`,
          background: active ? "#EDF4FA" : file ? "#F8FBF9" : "#FBFCFD",
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*,.pdf"
          onChange={(e) => handleFile(kind, e.target.files?.[0])}
          style={{ display: "none" }}
        />
        {!file && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
            <span style={{ fontSize: 18, color: "#8B9AA8" }}>⇱</span>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: colors.textHeading }}>
              {kind === "recto" ? "Recto de la traite" : "Verso de la traite"}
            </span>
            <span style={{ fontSize: 11, color: colors.textMuted }}>
              {kind === "recto" ? "Glisser le fichier ici ou cliquer pour parcourir" : "Zone d'endossement à l'ordre de SPG"}
            </span>
          </div>
        )}
        {file && (
          <span
            style={{
              position: "absolute",
              left: 8,
              bottom: 8,
              right: 8,
              fontFamily: fonts.mono,
              fontSize: 10.5,
              color: colors.greenText,
              background: "rgba(255,255,255,.92)",
              border: `1px solid ${colors.greenBorder}`,
              borderRadius: 3,
              padding: "3px 6px",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            ✓ {file.name}
          </span>
        )}
      </div>
    );
  }

  const total = listQuery.data?.total ?? 0;
  const nbPages = Math.max(1, Math.ceil(total / PER_PAGE));
  const counts = countsQuery.data?.par_statut;

  return (
    <div className="tp-page-pad" style={{ padding: "22px 26px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Nouvelle analyse */}
      <div style={{ background: "#fff", border: `1px solid ${colors.border}`, borderRadius: 6, overflow: "hidden" }}>
        <div
          className="tp-uploadhead"
          style={{ padding: "11px 14px", borderBottom: `1px solid ${colors.divider}`, display: "flex", alignItems: "center", gap: 9 }}
        >
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Nouvelle analyse — importer le scan d'une traite</span>
          <span style={{ fontSize: 11, color: colors.textMuted }}>
            Recto et verso obligatoires — les deux faces sont requises pour lancer l'analyse
          </span>
          <span style={{ marginLeft: "auto", fontSize: 10.5, color: colors.textMuted, fontFamily: fonts.mono }}>
            JPEG, PNG ou PDF · 300 dpi min.
          </span>
        </div>

        <div className="tp-dropzone-row" style={{ padding: 14, display: "flex", gap: 14, alignItems: "stretch" }}>
          {renderDropzone("recto")}
          {renderDropzone("verso")}
          <div
            className="tp-dropzone-action"
            style={{ width: 250, flex: "0 0 250px", display: "flex", flexDirection: "column", gap: 9, justifyContent: "center" }}
          >
            <span style={{ fontSize: 11.5, color: colors.textMuted, lineHeight: 1.5 }}>{uploadNote}</span>
            <button
              onClick={() => launchMutation.mutate()}
              disabled={!canStart || launchMutation.isPending}
              style={{
                border: "none",
                borderRadius: 5,
                padding: "10px 14px",
                fontSize: 12,
                fontWeight: 600,
                fontFamily: "inherit",
                cursor: canStart ? "pointer" : "not-allowed",
                background: canStart ? colors.navy900 : colors.dividerLight,
                color: canStart ? "#fff" : "#93A2B0",
              }}
            >
              {launchMutation.isPending ? "Envoi en cours…" : "Lancer l'analyse OCR / NLP"}
            </button>
            {(rectoFile || versoFile) && (
              <span
                onClick={() => {
                  setRectoFile(null);
                  setVersoFile(null);
                }}
                style={{ fontSize: 11, color: colors.textMuted, textAlign: "center", cursor: "pointer", textDecoration: "underline" }}
              >
                Retirer les fichiers
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Compteurs */}
      <div className="tp-counters" style={{ gap: 12 }}>
        {COUNTER_STATUSES.map((statut) => {
          const isActive = filter === statut;
          const label = statut === "Validée" ? "Validées" : statut;
          return (
            <div
              key={statut}
              onClick={() => {
                setFilter(isActive ? "Toutes" : statut);
                setPage(1);
              }}
              style={{
                background: "#fff",
                border: `1px solid ${isActive ? "#9FB3C8" : colors.border}`,
                borderTop: `3px solid ${COUNTER_ACCENTS[statut]}`,
                borderRadius: 5,
                padding: "12px 14px",
                cursor: "pointer",
                boxShadow: isActive ? "0 0 0 2px rgba(30,92,143,.12)" : undefined,
              }}
            >
              <div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.7, color: colors.textMuted }}>{label}</div>
              <div style={{ fontFamily: fonts.mono, fontSize: 23, fontWeight: 600, marginTop: 4, color: COUNTER_ACCENTS[statut] }}>
                {counts ? counts[statut] : "—"}
              </div>
            </div>
          );
        })}
      </div>

      {/* Table */}
      <div style={{ background: "#fff", border: `1px solid ${colors.border}`, borderRadius: 6, overflow: "hidden" }}>
        <div
          className="tp-tablehead"
          style={{ padding: "12px 16px", borderBottom: `1px solid ${colors.divider}`, display: "flex", alignItems: "center", gap: 10 }}
        >
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>Traites à contrôler</span>
          <span style={{ fontSize: 11.5, color: colors.textMuted }}>— tri par délai restant croissant</span>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", rowGap: 6 }}>
            <span style={{ fontSize: 11, color: colors.textMuted, marginRight: 2 }}>Statut :</span>
            {(["Toutes", ...ALL_STATUSES] as Filter[]).map((f) => {
              const isActive = filter === f;
              return (
                <div
                  key={f}
                  onClick={() => {
                    setFilter(f);
                    setPage(1);
                  }}
                  style={{
                    fontSize: 11,
                    padding: "4px 9px",
                    borderRadius: 4,
                    cursor: "pointer",
                    border: `1px solid ${isActive ? colors.navy900 : colors.borderInput}`,
                    background: isActive ? colors.navy900 : "#fff",
                    color: isActive ? "#fff" : colors.textSecondary,
                  }}
                >
                  {f}
                </div>
              );
            })}
          </div>
        </div>

        <div className="tp-table-scroll">
          <table className="tp-datatable" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
            <thead>
              <tr style={{ background: "#F5F7FA", color: "#546678" }}>
                {["N° L-CN", "Tireur (adhérent)", "Tiré (débiteur)", "Montant", "Échéance", "Reçue le", "Statut", "Délai (SLA 24h)", ""].map(
                  (label, i) => (
                    <th
                      key={label || i}
                      style={{
                        textAlign: label === "Montant" ? "right" : "left",
                        padding: label ? "9px 12px" : undefined,
                        fontSize: 10.5,
                        letterSpacing: 0.7,
                        textTransform: "uppercase",
                        fontWeight: 600,
                        borderBottom: `1px solid ${colors.divider}`,
                        width: label === "Délai (SLA 24h)" ? 148 : undefined,
                      }}
                    >
                      {label}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {listQuery.data?.items.map((traite) => {
                const sla = computeSla(traite.date_reception, traite.statut);
                return (
                  <tr key={traite.id} onClick={() => navigate(`/traites/${traite.id}`)} style={{ cursor: "pointer", background: "#fff" }}>
                    <td style={{ padding: "11px 16px", borderBottom: `1px solid ${colors.dividerLight}`, fontFamily: fonts.mono, fontWeight: 500 }}>
                      {traite.numero_lcn}
                    </td>
                    <td style={{ padding: "11px 12px", borderBottom: `1px solid ${colors.dividerLight}`, fontWeight: 600 }}>
                      {traite.tireur_nom ?? "—"}
                    </td>
                    <td style={{ padding: "11px 12px", borderBottom: `1px solid ${colors.dividerLight}`, color: colors.textSecondary }}>
                      {traite.tire_nom ?? "—"}
                    </td>
                    <td style={{ padding: "11px 12px", borderBottom: `1px solid ${colors.dividerLight}`, textAlign: "right", fontFamily: fonts.mono }}>
                      {formatMontant(traite.montant)}
                    </td>
                    <td style={{ padding: "11px 12px", borderBottom: `1px solid ${colors.dividerLight}`, fontFamily: fonts.mono, color: colors.textSecondary }}>
                      {formatDate(traite.date_echeance)}
                    </td>
                    <td style={{ padding: "11px 12px", borderBottom: `1px solid ${colors.dividerLight}`, fontFamily: fonts.mono, color: colors.textSecondary }}>
                      {formatDateTime(traite.date_reception)}
                    </td>
                    <td style={{ padding: "11px 12px", borderBottom: `1px solid ${colors.dividerLight}` }}>
                      <StatusBadge statut={traite.statut} />
                    </td>
                    <td style={{ padding: "11px 12px", borderBottom: `1px solid ${colors.dividerLight}` }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ fontSize: 11, fontFamily: fonts.mono, color: sla.color, fontWeight: 500 }}>{sla.label}</span>
                        <div style={{ height: 5, borderRadius: 3, background: colors.divider, overflow: "hidden" }}>
                          <div style={{ width: `${sla.percent}%`, height: "100%", background: sla.color }} />
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: "11px 16px 11px 4px", borderBottom: `1px solid ${colors.dividerLight}`, textAlign: "right", color: "#9AA9B7" }}>
                      ›
                    </td>
                  </tr>
                );
              })}
              {listQuery.data?.items.length === 0 && (
                <tr>
                  <td colSpan={9} style={{ padding: "24px 16px", textAlign: "center", color: colors.textMuted }}>
                    Aucune traite pour ce filtre.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div
          className="tp-pagerow"
          style={{ padding: "10px 16px", borderTop: `1px solid ${colors.divider}`, background: colors.bgSubtle, display: "flex", alignItems: "center", gap: 8 }}
        >
          <span style={{ fontSize: 11.5, color: colors.textMuted }}>
            {total === 0 ? "Aucune traite" : `${(page - 1) * PER_PAGE + 1}–${Math.min(page * PER_PAGE, total)} sur ${total} traites`}
          </span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", rowGap: 6 }}>
            <div
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              style={{
                fontSize: 11,
                padding: "5px 10px",
                borderRadius: 4,
                border: `1px solid ${colors.borderInput}`,
                background: "#fff",
                color: page > 1 ? colors.textSecondary : "#B6C2CE",
                cursor: page > 1 ? "pointer" : "not-allowed",
              }}
            >
              ‹ Précédent
            </div>
            {Array.from({ length: nbPages }, (_, i) => i + 1).map((num) => (
              <div
                key={num}
                onClick={() => setPage(num)}
                style={{
                  minWidth: 26,
                  textAlign: "center",
                  fontSize: 11,
                  fontFamily: fonts.mono,
                  padding: "5px 8px",
                  borderRadius: 4,
                  cursor: "pointer",
                  border: `1px solid ${page === num ? colors.navy900 : colors.borderInput}`,
                  background: page === num ? colors.navy900 : "#fff",
                  color: page === num ? "#fff" : colors.textSecondary,
                }}
              >
                {num}
              </div>
            ))}
            <div
              onClick={() => setPage((p) => Math.min(nbPages, p + 1))}
              style={{
                fontSize: 11,
                padding: "5px 10px",
                borderRadius: 4,
                border: `1px solid ${colors.borderInput}`,
                background: "#fff",
                color: page < nbPages ? colors.textSecondary : "#B6C2CE",
                cursor: page < nbPages ? "pointer" : "not-allowed",
              }}
            >
              Suivant ›
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
