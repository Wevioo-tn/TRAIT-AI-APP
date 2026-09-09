import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import * as api from "../api/client";
import { ApiError } from "../api/client";
import type {
  ChampExtraitRead,
  Face,
  StatutVerification,
  TraiteDetail,
  VerificationCode,
} from "../api/types";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../components/ToastProvider";
import { formatDate, formatDateTime, formatMontant } from "../lib/format";
import { colors, fonts } from "../theme";

const CHAMP_LABELS: Record<string, string> = {
  numero_lcn: "N° L-CN",
  montant_chiffres: "Montant en chiffres",
  echeance: "Échéance",
  date_creation: "Date de création",
  rib_tire: "RIB tiré",
  lieu_creation: "Lieu de création",
  // The RIB's own 4 printed sub-fields (UC-01, étape 4) — a second,
  // independent reconstruction of the same 20-digit RIB rib_tire reads
  // directly, not a redundant re-listing of it.
  code_etablissement: "Code établissement",
  code_agence: "Code agence",
  numero_compte: "N° de compte",
  cle_rib: "Clé RIB",
};

// Not shown in the "Contrôle de cohérence des champs dupliqués" table (per
// your call) — the data itself is untouched, this is a display filter only.
const CHAMPS_HIDDEN_FROM_COHERENCE_TABLE = new Set(["montant_lettres"]);

const PROCESSING_PHASES = [
  "Lecture du scan · binarisation et détection des zones",
  "Extraction OCR des champs dupliqués",
  "Rapprochement NLP tireur / tiré au référentiel IMX",
  "Contrôle des mentions, des dates et du RIB",
];

const CHECK_LABELS: Record<VerificationCode, { label: string; face: Face; hint: string }> = {
  sigTire: { label: "Signature du tiré", face: "recto", hint: "Cachet/signature dans la case du tiré." },
  accept: { label: "Mention d'acceptation", face: "recto", hint: "Cachet et paraphe dans la case Acceptation." },
  sigTireur: { label: "Signature du tireur + cachet", face: "recto", hint: "Contrôle contre l'original si case vide au scan." },
  endos: { label: "Endossement à l'ordre de SPG", face: "verso", hint: "Cachet et signature de l'adhérent." },
};

const card: React.CSSProperties = {
  background: "#fff",
  border: `1px solid ${colors.border}`,
  borderRadius: 6,
  overflow: "hidden",
};
const cardHeader: React.CSSProperties = {
  padding: "10px 14px",
  borderBottom: `1px solid ${colors.divider}`,
  display: "flex",
  alignItems: "center",
  gap: 9,
};

export default function AnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const queryClient = useQueryClient();

  const detailQuery = useQuery({
    queryKey: ["traites", id],
    queryFn: () => api.getTraite(id as string),
    enabled: !!id,
  });

  const isProcessing = detailQuery.data?.statut === "En cours OCR";

  // Purely descriptive of the pipeline's real stages (extraction ->
  // NLP matching -> mentions/date checks) — not tied to any actual
  // progress signal from the backend, which only ever reports en_cours
  // true/false (see GET .../status). Deliberately no percentage/fake
  // progress bar here: this app already replaced that kind of fabricated
  // completion signal with real polling once (Sprint 6) and shouldn't
  // reintroduce it just for a nicer-looking wait.
  const [phaseIndex, setPhaseIndex] = useState(0);
  useEffect(() => {
    if (!isProcessing) {
      setPhaseIndex(0);
      return;
    }
    const interval = setInterval(() => setPhaseIndex((i) => (i + 1) % PROCESSING_PHASES.length), 2400);
    return () => clearInterval(interval);
  }, [isProcessing]);

  const statusQuery = useQuery({
    queryKey: ["traites", id, "status"],
    queryFn: () => api.getTraiteStatus(id as string),
    enabled: !!id && isProcessing,
    refetchInterval: isProcessing ? 2000 : false,
  });

  useEffect(() => {
    if (statusQuery.data && !statusQuery.data.en_cours) {
      queryClient.invalidateQueries({ queryKey: ["traites", id] });
      queryClient.invalidateQueries({ queryKey: ["traites"] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusQuery.data?.en_cours]);

  const verifyMutation = useMutation({
    mutationFn: ({ code, statut }: { code: VerificationCode; statut: StatutVerification | null }) =>
      api.updateVerification(id as string, code, statut),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["traites", id] }),
    onError: (error: unknown) => {
      toast.show("ko", "Action impossible", error instanceof ApiError ? error.message : "Erreur inattendue.");
    },
  });

  const montantAvoirsMutation = useMutation({
    mutationFn: (montantAvoirs: number | null) => api.updateMontantAvoirs(id as string, montantAvoirs),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["traites", id] }),
    onError: (error: unknown) => {
      toast.show("ko", "Action impossible", error instanceof ApiError ? error.message : "Erreur inattendue.");
    },
  });

  if (detailQuery.isLoading) {
    return <div className="tp-page-pad" style={{ padding: 26, color: colors.textMuted }}>Chargement…</div>;
  }
  if (detailQuery.isError || !detailQuery.data) {
    return (
      <div className="tp-page-pad" style={{ padding: 26 }}>
        <Link to="/" style={{ color: colors.blue700 }}>← Liste des traites</Link>
        <p style={{ color: colors.redText }}>Traite introuvable.</p>
      </div>
    );
  }

  const traite = detailQuery.data;
  const rectoDoc = traite.documents.find((d) => d.face === "recto");
  const versoDoc = traite.documents.find((d) => d.face === "verso");
  const hasDecision = traite.decisions.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <SummaryHeader traite={traite} />

      <div
        className="tp-analyse-grid tp-page-pad"
        style={{ padding: "18px 26px 44px", gap: 16 }}
      >
        <div>
          <div className="tp-doc-sticky" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={card}>
              <div style={cardHeader}>
                <span style={{ fontSize: 12.5, fontWeight: 600 }}>Recto — {traite.numero_lcn}</span>
              </div>
              <div
                className="tp-doc-scroll"
                style={{ padding: 16, background: "#E9EDF2", minHeight: 300, position: "relative", overflow: "hidden" }}
              >
                <DocumentViewer traiteId={traite.id} document={rectoDoc} face="recto" />
                {isProcessing && <ScanningOverlay label={PROCESSING_PHASES[phaseIndex]} />}
              </div>
            </div>

            <div style={card}>
              <div style={cardHeader}>
                <span style={{ fontSize: 12.5, fontWeight: 600 }}>Verso · endossement — {traite.numero_lcn}</span>
              </div>
              <div
                className="tp-doc-scroll"
                style={{ padding: 16, background: "#E9EDF2", minHeight: 300, position: "relative", overflow: "hidden" }}
              >
                <DocumentViewer traiteId={traite.id} document={versoDoc} face="verso" />
                {isProcessing && <ScanningOverlay label={PROCESSING_PHASES[phaseIndex]} />}
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {isProcessing ? (
            <>
              <SkeletonCard title="Verdict de l'agent" rows={3} />
              <SkeletonCard title="Avoirs par débiteur (saisie manuelle)" rows={2} />
              <SkeletonCard title="Mentions obligatoires de la lettre de change" rows={4} />
              <SkeletonCard title="Contrôle de cohérence des champs dupliqués" rows={4} />
              <SkeletonCard title="Contrôles de dates" rows={3} />
              <SkeletonCard title="Rapprochement NLP au référentiel IMX" rows={2} />
              <SkeletonCard title="Vérifications manuelles obligatoires" rows={4} />
            </>
          ) : (
            <>
              <VerdictCard traite={traite} />
              <AvoirsCard
                traite={traite}
                disabled={hasDecision}
                onSave={(montantAvoirs) => montantAvoirsMutation.mutate(montantAvoirs)}
              />
              <MentionsCard traite={traite} />
              <ChampsCard traite={traite} />
              <DateRulesCard traite={traite} />
              <NlpCard traite={traite} />
              <ChecksCard
                traite={traite}
                onSet={(code, statut) => verifyMutation.mutate({ code, statut })}
                disabled={hasDecision}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryHeader({ traite }: { traite: TraiteDetail }) {
  const items: [string, string][] = [
    ["N° L-CN", traite.numero_lcn],
    ["Tireur", traite.tireur_nom ?? "Non résolu"],
    ["Tiré", traite.tire_nom ?? "Non résolu"],
    ["Montant · échéance", `${formatMontant(traite.montant)} · ${formatDate(traite.date_echeance)}`],
  ];
  return (
    <div
      className="tp-analyse-summary tp-page-pad"
      style={{ background: "#fff", borderBottom: `1px solid ${colors.border}`, padding: "10px 26px", display: "flex", alignItems: "center", gap: 18 }}
    >
      <Link to="/" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: colors.blue700, fontWeight: 500 }}>
        ← Liste des traites
      </Link>
      {items.map(([label, value]) => (
        <div key={label} style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div className="tp-vdivider" style={{ width: 1, height: 30, background: colors.divider }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.7, color: colors.textMuted }}>{label}</span>
            <span style={{ fontFamily: fonts.mono, fontSize: 13, fontWeight: 600 }}>{value}</span>
          </div>
        </div>
      ))}
      <div style={{ marginLeft: "auto" }}>
        <StatusBadge statut={traite.statut} />
      </div>
    </div>
  );
}

// The dark scanning overlay sits on top of the traite's own already-
// uploaded scan (not a generic placeholder) while extraction runs — ported
// from the validated design mockup's `scanline`/`spin` keyframes
// (global.css). Deliberately no percentage or fill bar: the mockup's
// version faked a fixed-duration completion, which is exactly what real
// polling (Sprint 6) replaced — reintroducing a fake number here would be
// a step backwards, so the label only ever names a plausible current step,
// never implies how much is left.
function ScanningOverlay({ label }: { label: string }) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "rgba(11,34,57,.78)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 14,
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 0,
          height: 2,
          background: "linear-gradient(90deg,transparent,#4FA3E3,transparent)",
          animation: "scanline 1.9s linear infinite",
        }}
      />
      <div
        style={{
          width: 26,
          height: 26,
          border: "2.5px solid rgba(255,255,255,.25)",
          borderTopColor: "#7EC0F5",
          borderRadius: "50%",
          animation: "spin .9s linear infinite",
        }}
      />
      <div style={{ color: "#E8F1F9", fontSize: 12.5, fontWeight: 500, textAlign: "center", maxWidth: 320, padding: "0 20px" }}>
        {label}
      </div>
    </div>
  );
}

const SKELETON_ROW_WIDTHS = [86, 62, 78, 48, 92, 66];

// Mirrors the real cards' own `card`/`cardHeader` shell and title, so the
// layout doesn't jump when real data replaces it — only the body swaps
// from shimmering placeholder bars to actual content.
function SkeletonCard({ title, rows }: { title: string; rows: number }) {
  return (
    <div style={card}>
      <div style={cardHeader}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{title}</span>
      </div>
      <div style={{ padding: "14px", display: "flex", flexDirection: "column", gap: 10 }}>
        {Array.from({ length: rows }, (_, i) => (
          <div
            key={i}
            style={{
              height: 11,
              borderRadius: 3,
              background: colors.bgPage,
              width: `${SKELETON_ROW_WIDTHS[i % SKELETON_ROW_WIDTHS.length]}%`,
              animation: `pulse 1.4s infinite ${i * 0.15}s`,
            }}
          />
        ))}
      </div>
    </div>
  );
}

function DocumentViewer({
  traiteId,
  document,
  face,
}: {
  traiteId: string;
  document: { content_type: string; fichier_nom: string } | undefined;
  face: Face;
}) {
  // The document endpoint requires the same Bearer token as every other
  // route now — a plain <img src>/<a href> URL can't carry it, so the
  // bytes are fetched here and turned into a same-origin object URL.
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!document) {
      setObjectUrl(null);
      return;
    }
    let cancelled = false;
    let url: string | null = null;
    api.getDocumentBlob(traiteId, face).then((blob) => {
      if (cancelled) return;
      url = URL.createObjectURL(blob);
      setObjectUrl(url);
    });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [traiteId, face, document]);

  if (!document) {
    return <div style={{ color: colors.textMuted, fontSize: 12 }}>Aucun fichier {face} importé.</div>;
  }
  if (!objectUrl) {
    return <div style={{ color: colors.textMuted, fontSize: 12 }}>Chargement du document…</div>;
  }
  if (document.content_type === "application/pdf") {
    return (
      <a href={objectUrl} target="_blank" rel="noreferrer" style={{ fontSize: 12.5, color: colors.blue700 }}>
        Ouvrir le PDF ({document.fichier_nom})
      </a>
    );
  }
  return (
    <img src={objectUrl} alt={`${face} de la traite`} style={{ maxWidth: "100%", display: "block", margin: "0 auto" }} />
  );
}

function VerdictCard({ traite }: { traite: TraiteDetail }) {
  const checkCount = traite.verifications_manuelles.filter((v) => v.statut !== null).length;
  return (
    <div style={card}>
      <div style={cardHeader}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Verdict de l'agent</span>
      </div>
      <div className="tp-verdict-grid">
        <div style={{ padding: "12px 14px", borderRight: `1px solid ${colors.dividerLight}`, display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.7, color: colors.textMuted }}>Contrôles manuels</span>
          <span style={{ fontFamily: fonts.mono, fontSize: 19, fontWeight: 600, color: colors.purple }}>{checkCount} / 4</span>
          <span style={{ fontSize: 11, color: colors.textMuted }}>zones statuées</span>
        </div>
        <div style={{ padding: "12px 14px", borderRight: `1px solid ${colors.dividerLight}`, display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.7, color: colors.textMuted }}>Facture rapprochée</span>
          <span style={{ fontFamily: fonts.mono, fontSize: 15, fontWeight: 600 }}>{traite.num_facture_rapprochee ?? "—"}</span>
          <span style={{ fontSize: 11, color: colors.textMuted }}>référentiel IMX</span>
        </div>
        <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.7, color: colors.textMuted }}>État</span>
          <span style={{ fontFamily: fonts.mono, fontSize: 15, fontWeight: 600, color: traite.bloque ? colors.orange : colors.green }}>
            {traite.bloque ? "Bloqué" : "Prêt"}
          </span>
        </div>
      </div>
      <div style={{ padding: "12px 14px", borderTop: `1px solid ${colors.dividerLight}`, background: traite.bloque ? "#FDF1E2" : "#E8F4ED" }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: traite.bloque ? colors.orangeText : colors.greenText }}>
          {traite.recommandation.titre}
        </div>
        <div style={{ fontSize: 11.5, color: traite.bloque ? "#8A5312" : colors.greenText, lineHeight: 1.5, marginTop: 3 }}>
          {traite.recommandation.detail}
        </div>
      </div>
      {traite.control_rollup && <ControlRollupStrip rollup={traite.control_rollup} />}
    </div>
  );
}

// BPMN Phase 2, étape 10 — "Visualiser le résultat OK/KO par rubrique sur
// l'écran principal", rolled up across every bill this app currently
// knows for this bill's resolved débiteur (not scoped to "this remise"
// yet — see backend's app/services/control_rollup.py). A rollup of
// verdicts already shown in detail elsewhere on this page, not new
// information — hence a compact strip here, not another full card.
type ControlRollup = NonNullable<TraiteDetail["control_rollup"]>;

const RUBRIQUE_LABELS: [keyof ControlRollup, string][] = [
  ["mandatory_mentions_ok", "Mentions"],
  ["duplicated_fields_ok", "Champs dupliqués"],
  ["date_rules_ok", "Dates"],
  ["identification_ok", "Identification"],
  ["coverage_ok", "Couverture"],
];

function ControlRollupStrip({ rollup }: { rollup: ControlRollup }) {
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 6,
        padding: "9px 14px",
        borderTop: `1px solid ${colors.dividerLight}`,
        background: "#F7F9FB",
      }}
    >
      {RUBRIQUE_LABELS.map(([key, label]) => {
        const ok = rollup[key];
        return (
          <span
            key={key}
            title="Débiteur — toutes traites connues (hors remise)"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              fontSize: 10.5,
              fontWeight: 600,
              padding: "2px 8px",
              borderRadius: 11,
              whiteSpace: "nowrap",
              color: ok ? colors.greenText : colors.orangeText,
              background: ok ? colors.greenBg : colors.orangeBg,
              border: `1px solid ${ok ? colors.greenBorder : colors.orangeBorder}`,
            }}
          >
            {ok ? "✓" : "✗"} {label}
          </span>
        );
      })}
    </div>
  );
}

const avoirsInputStyle: React.CSSProperties = {
  border: `1px solid ${colors.borderInput}`,
  borderRadius: 5,
  padding: "6px 9px",
  fontFamily: fonts.mono,
  fontSize: 12.5,
  color: colors.textPrimary,
  outline: "none",
  width: 130,
};

// BPMN Phase 3, étape 2 (Caissier) — "Saisir manuellement les montants des
// avoirs par débiteur si applicable". The facture's own montant_ttc/
// montant_avoirs/montant_net come straight from the read-only IMX
// referential (facture_rapprochee) and are never editable here — only
// montant_avoirs_saisi is, and it's this app's own observation, not a
// correction of that IMX data (see backend's FactureRapprocheeRead
// docstring for the same distinction on the API side).
function AvoirsCard({
  traite,
  disabled,
  onSave,
}: {
  traite: TraiteDetail;
  disabled: boolean;
  onSave: (montantAvoirs: number | null) => void;
}) {
  const [draft, setDraft] = useState(traite.montant_avoirs_saisi ?? "");

  useEffect(() => {
    setDraft(traite.montant_avoirs_saisi ?? "");
  }, [traite.montant_avoirs_saisi]);

  const facture = traite.facture_rapprochee;

  function commit() {
    if (draft.trim() === "") {
      onSave(null);
      return;
    }
    const parsed = Number(draft);
    if (!Number.isNaN(parsed)) onSave(parsed);
  }

  return (
    <div style={card}>
      <div style={cardHeader}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Avoirs par débiteur</span>
      </div>
      <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.6, color: colors.textMuted }}>
            Référentiel IMX (lecture seule){facture ? ` — facture ${facture.num_facture}` : ""}
          </span>
          {facture ? (
            <span style={{ fontSize: 12, fontFamily: fonts.mono }}>
              TTC {formatMontant(facture.montant_ttc)} · Avoirs {formatMontant(facture.montant_avoirs)} · Net{" "}
              {formatMontant(facture.montant_net)}
            </span>
          ) : (
            <span style={{ fontSize: 11.5, color: colors.textMuted }}>Aucune facture rapprochée.</span>
          )}
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, color: colors.textHeading, whiteSpace: "nowrap" }}>
            Avoirs saisis (DT)
          </span>
          <input
            type="number"
            min="0"
            step="0.001"
            placeholder="Si applicable…"
            value={draft}
            disabled={disabled}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            style={{ ...avoirsInputStyle, opacity: disabled ? 0.6 : 1 }}
          />
        </label>
        {traite.debtor_coverage && <CoverageSummary coverage={traite.debtor_coverage} />}
      </div>
    </div>
  );
}

// BPMN Phase 3, étape 3 — "Contrôler la couverture des factures par les
// IP par débiteur". Aggregated across every bill this app currently
// knows about for this débiteur (not scoped to "this remise" yet — see
// backend's app/services/coverage.py), so these totals can differ from
// this one bill's own numbers above. coverage_gap_threshold is a working
// hypothesis (see Settings.coverage_gap_threshold's own docstring), never
// presented here as a definitive spec value.
function CoverageSummary({ coverage }: { coverage: NonNullable<TraiteDetail["debtor_coverage"]> }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        borderTop: `1px solid ${colors.dividerLight}`,
        paddingTop: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: 0.6, color: colors.textMuted }}>
          Couverture facture/IP du débiteur — toutes traites connues
        </span>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            padding: "2px 8px",
            borderRadius: 11,
            whiteSpace: "nowrap",
            color: coverage.sufficient ? colors.greenText : colors.orangeText,
            background: coverage.sufficient ? colors.greenBg : colors.orangeBg,
            border: `1px solid ${coverage.sufficient ? colors.greenBorder : colors.orangeBorder}`,
          }}
        >
          {coverage.sufficient ? "Couverture suffisante" : "Couverture insuffisante"}
        </span>
      </div>
      <div style={{ fontSize: 12, fontFamily: fonts.mono, color: colors.textHeading }}>
        Traites {formatMontant(coverage.total_bills_amount)} · Factures nettes{" "}
        {formatMontant(coverage.total_invoices_net_amount)} · Avoirs saisis{" "}
        {formatMontant(coverage.total_credit_notes_amount)}
      </div>
      <div style={{ fontSize: 11.5, color: coverage.sufficient ? colors.greenText : colors.orangeText }}>
        Écart : {formatMontant(coverage.gap)}
      </div>
    </div>
  );
}

function mentionIcon(statut: string): { icon: string; bg: string } {
  if (statut === "ok") return { icon: "✓", bg: colors.green };
  if (statut === "warn") return { icon: "!", bg: colors.orange };
  return { icon: "✗", bg: colors.red };
}

function MentionsCard({ traite }: { traite: TraiteDetail }) {
  return (
    <div style={card}>
      <div style={cardHeader}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Mentions obligatoires de la lettre de change</span>
      </div>
      <div className="tp-mentions-grid">
        {traite.mentions.map((m) => {
          const { icon, bg } = mentionIcon(m.statut);
          return (
            <div key={m.code} style={{ display: "flex", alignItems: "flex-start", gap: 9, padding: "9px 14px", borderBottom: `1px solid ${colors.dividerLight}` }}>
              <span style={{ width: 16, height: 16, flex: "0 0 16px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: "#fff", background: bg, marginTop: 1 }}>
                {icon}
              </span>
              <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                <span style={{ fontSize: 11.5, fontWeight: 600, color: colors.textHeading }}>{m.label}</span>
                <span style={{ fontSize: 10.5, color: colors.textMuted, lineHeight: 1.4 }}>{m.valeur ?? "Non disponible"}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChampsCard({ traite }: { traite: TraiteDetail }) {
  const byChamp = new Map<string, ChampExtraitRead[]>();
  for (const champ of traite.champs_extraits) {
    if (CHAMPS_HIDDEN_FROM_COHERENCE_TABLE.has(champ.nom_champ)) continue;
    if (!byChamp.has(champ.nom_champ)) byChamp.set(champ.nom_champ, []);
    byChamp.get(champ.nom_champ)!.push(champ);
  }

  return (
    <div style={card}>
      <div style={cardHeader}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Contrôle de cohérence des champs dupliqués</span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ background: colors.bgSubtle, color: "#546678" }}>
            {["Champ", "Occurrence 1", "Occurrence 2", "Verdict"].map((h, i) => (
              <th key={h} style={{ textAlign: i === 3 ? "right" : "left", padding: "7px 14px", fontSize: 10, letterSpacing: 0.6, textTransform: "uppercase", fontWeight: 600, borderBottom: `1px solid ${colors.divider}` }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...byChamp.entries()].map(([nom, occurrences]) => {
            const occ1 = occurrences.find((c) => c.occurrence === 1)?.valeur ?? null;
            const occ2 = occurrences.find((c) => c.occurrence === 2)?.valeur ?? null;
            const coherent = occ1 === occ2;
            return (
              <tr key={nom}>
                <td style={{ padding: "9px 14px", borderBottom: `1px solid ${colors.dividerLight}`, fontWeight: 600, color: colors.textHeading, verticalAlign: "top" }}>
                  {CHAMP_LABELS[nom] ?? nom}
                </td>
                <td style={{ padding: "9px 10px", borderBottom: `1px solid ${colors.dividerLight}`, fontFamily: fonts.mono, fontSize: 11.5, verticalAlign: "top" }}>
                  {occ1 ?? "—"}
                </td>
                <td style={{ padding: "9px 10px", borderBottom: `1px solid ${colors.dividerLight}`, fontFamily: fonts.mono, fontSize: 11.5, verticalAlign: "top" }}>
                  {occ2 ?? "—"}
                </td>
                <td style={{ padding: "9px 14px", borderBottom: `1px solid ${colors.dividerLight}`, textAlign: "right", verticalAlign: "top" }}>
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "2px 8px",
                      borderRadius: 11,
                      whiteSpace: "nowrap",
                      color: coherent ? colors.greenText : colors.orangeText,
                      background: coherent ? colors.greenBg : colors.orangeBg,
                      border: `1px solid ${coherent ? colors.greenBorder : colors.orangeBorder}`,
                    }}
                  >
                    {coherent ? "✓ Cohérent" : "⚠ Écart"}
                  </span>
                </td>
              </tr>
            );
          })}
          {byChamp.size === 0 && (
            <tr>
              <td colSpan={4} style={{ padding: "16px 14px", textAlign: "center", color: colors.textMuted }}>
                Analyse pas encore lancée.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function DateRulesCard({ traite }: { traite: TraiteDetail }) {
  return (
    <div style={card}>
      <div style={cardHeader}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Contrôles de dates</span>
      </div>
      {traite.regles_dates.map((r) => {
        const icon = r.ok === null ? "?" : r.ok ? "✓" : "!";
        const bg = r.ok === null ? colors.textMuted : r.ok ? colors.green : colors.orange;
        return (
          <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 9, padding: "9px 14px", borderBottom: `1px solid ${colors.dividerLight}` }}>
            <span style={{ width: 16, height: 16, flex: "0 0 16px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: "#fff", background: bg }}>
              {icon}
            </span>
            <span style={{ fontSize: 12, fontWeight: 600, color: colors.textHeading, flex: 1 }}>{r.label}</span>
            <span style={{ fontFamily: fonts.mono, fontSize: 11.5, color: colors.textSecondary }}>
              {r.valeur_a && r.valeur_b ? `${r.valeur_a} / ${r.valeur_b}` : "indéterminé"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function NlpCard({ traite }: { traite: TraiteDetail }) {
  return (
    <div style={card}>
      <div style={cardHeader}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Rapprochement NLP au référentiel IMX</span>
      </div>
      {traite.rapprochements_nlp.map((n) => {
        const score = Number(n.score);
        const ok = score >= 95;
        const viaRib = n.methode_identification === "rib";
        return (
          <div key={n.id} style={{ padding: "11px 14px", borderBottom: `1px solid ${colors.dividerLight}`, display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, color: colors.textMuted, width: 44 }}>{n.role}</span>
              <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0, flex: 1 }}>
                <span style={{ fontSize: 12 }}>
                  <b>{n.valeur_scan || "—"}</b> <span style={{ color: "#8B9AA8" }}>↔</span> {n.valeur_referentiel ?? "aucune correspondance"}
                </span>
                <div style={{ height: 5, borderRadius: 3, background: colors.divider, overflow: "hidden", maxWidth: 240 }}>
                  <div style={{ width: `${Math.min(100, score)}%`, height: "100%", background: ok ? colors.green : colors.orange }} />
                </div>
              </div>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  padding: "2px 8px",
                  borderRadius: 11,
                  color: ok ? colors.greenText : colors.orangeText,
                  background: ok ? colors.greenBg : colors.orangeBg,
                  border: `1px solid ${ok ? colors.greenBorder : colors.orangeBorder}`,
                }}
              >
                {score.toFixed(0)} %
              </span>
            </div>
            {/* A reviewer must know whether they're confirming a hard key
                (a RIB hit, unique in imx.debiteurs) or a fuzzy name guess
                that still needs manual confirmation — a bare score can't
                tell them that (see BACKLOG.md's RIB-first identification
                story). */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: 56 }}>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  padding: "1px 7px",
                  borderRadius: 9,
                  whiteSpace: "nowrap",
                  color: viaRib ? colors.greenText : colors.orangeText,
                  background: viaRib ? colors.greenBg : colors.orangeBg,
                  border: `1px solid ${viaRib ? colors.greenBorder : colors.orangeBorder}`,
                }}
              >
                {viaRib ? "Identifié par RIB" : "Nom seul — à confirmer"}
              </span>
              {n.alerte_ecart_nom && (
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    padding: "1px 7px",
                    borderRadius: 9,
                    whiteSpace: "nowrap",
                    color: colors.redText,
                    background: colors.redBg,
                    border: `1px solid ${colors.redBorder}`,
                  }}
                >
                  ⚑ RIB confirmé mais nom incohérent
                </span>
              )}
            </div>
          </div>
        );
      })}
      {traite.rapprochements_nlp.length === 0 && (
        <div style={{ padding: "16px 14px", textAlign: "center", color: colors.textMuted, fontSize: 12 }}>
          Analyse pas encore lancée.
        </div>
      )}
    </div>
  );
}

function ChecksCard({
  traite,
  onSet,
  disabled,
}: {
  traite: TraiteDetail;
  onSet: (code: VerificationCode, statut: StatutVerification | null) => void;
  disabled: boolean;
}) {
  const checkCount = traite.verifications_manuelles.filter((v) => v.statut !== null).length;
  return (
    <div style={{ ...card, border: "1px solid #C9B8E0" }}>
      <div style={{ ...cardHeader, background: "#F6F2FB", borderBottom: "1px solid #E4D9F2" }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: colors.purpleTextDark }}>Vérifications manuelles obligatoires</span>
        <span style={{ marginLeft: "auto", fontSize: 11, fontFamily: fonts.mono, color: colors.purpleText, fontWeight: 600 }}>{checkCount} / 4</span>
      </div>
      {traite.verifications_manuelles.map((v) => {
        const meta = CHECK_LABELS[v.code_verification];
        return (
          <div key={v.id} className="tp-check-row" style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", borderBottom: `1px solid ${colors.dividerLight}` }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ fontSize: 12.5, fontWeight: 600, color: colors.textHeading }}>{meta.label}</span>
                <span style={{ fontSize: 10, color: colors.purpleText, background: "#F1E9FA", borderRadius: 3, padding: "1px 5px" }}>
                  {meta.face === "recto" ? "Recto" : "Verso"}
                </span>
              </div>
              <span style={{ fontSize: 11, color: colors.textMuted, lineHeight: 1.45 }}>{meta.hint}</span>
            </div>
            <div className="tp-check-actions" style={{ display: "flex", gap: 6, flex: "0 0 auto" }}>
              <button
                disabled={disabled}
                onClick={() => onSet(v.code_verification, v.statut === "conforme" ? null : "conforme")}
                style={checkButtonStyle(v.statut === "conforme", colors.greenText, colors.greenBg, colors.greenBorder, disabled)}
              >
                ✓ Conforme
              </button>
              <button
                disabled={disabled}
                onClick={() => onSet(v.code_verification, v.statut === "anomalie" ? null : "anomalie")}
                style={checkButtonStyle(v.statut === "anomalie", colors.redText, colors.redBg, colors.redBorder, disabled)}
              >
                ⚑ Anomalie
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function checkButtonStyle(active: boolean, fg: string, bg: string, border: string, disabled: boolean): React.CSSProperties {
  return {
    fontSize: 10.5,
    fontWeight: 600,
    padding: "4px 9px",
    borderRadius: 4,
    cursor: disabled ? "not-allowed" : "pointer",
    whiteSpace: "nowrap",
    border: `1px solid ${active ? border : colors.borderInput}`,
    background: active ? bg : "#fff",
    color: active ? fg : colors.textMuted,
    opacity: disabled ? 0.6 : 1,
  };
}

