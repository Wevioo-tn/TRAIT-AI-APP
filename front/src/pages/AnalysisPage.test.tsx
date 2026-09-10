import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
import { ApiError } from "../api/client";
import type { TraiteDetail } from "../api/types";
import { renderWithProviders } from "../test/test-utils";
import AnalysisPage from "./AnalysisPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getTraite: vi.fn(),
    getTraiteStatus: vi.fn(),
    updateVerification: vi.fn(),
    updateMontantAvoirs: vi.fn(),
    createDecision: vi.fn(),
    getDocumentBlob: vi.fn(),
  };
});

const mockedApi = vi.mocked(api);

function baseTraite(overrides: Partial<TraiteDetail> = {}): TraiteDetail {
  return {
    id: "t1",
    numero_lcn: "011570763437",
    montant: "8117.504",
    date_echeance: "2026-08-28",
    date_creation_traite: "2026-08-05",
    date_reception: new Date().toISOString(),
    statut: "Contrôle manuel requis",
    code_adherent: "ADH-1001",
    code_debiteur: "DEB-1001",
    tireur_nom: "ADACTIM",
    tire_nom: "LA MÉDITERRANÉENNE",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    documents: [],
    champs_extraits: [
      { id: "c1", nom_champ: "echeance", occurrence: 1, valeur: "2026-08-28", source: "ocr", confiance: null },
      { id: "c2", nom_champ: "echeance", occurrence: 2, valeur: "2026-08-28", source: "ocr", confiance: null },
    ],
    rapprochements_nlp: [
      {
        id: "n1",
        role: "tireur",
        valeur_scan: "ADACTIM",
        valeur_referentiel: "ADACTIM",
        score: "100.00",
        code_adherent_matche: "ADH-1001",
        code_debiteur_matche: null,
        methode_identification: "nom_seul",
        alerte_ecart_nom: false,
      },
    ],
    verifications_manuelles: [
      { id: "v1", code_verification: "sigTire", statut: null, verifie_par: null, verifie_le: null },
      { id: "v2", code_verification: "accept", statut: null, verifie_par: null, verifie_le: null },
      { id: "v3", code_verification: "sigTireur", statut: null, verifie_par: null, verifie_le: null },
      { id: "v4", code_verification: "endos", statut: null, verifie_par: null, verifie_le: null },
    ],
    decisions: [],
    bloque: true,
    motif_blocage: "Vérifications manuelles incomplètes (0 / 4)",
    recommandation: { titre: "Terminer les vérifications manuelles", detail: "Les 4 zones restantes..." },
    mentions: [{ code: "nom_tire", label: "Nom du tiré", valeur: "LA MÉDITERRANÉENNE", statut: "ok" }],
    regles_dates: [
      { label: "Date de création ≤ date du jour", valeur_a: "2026-08-05", valeur_b: "2026-09-01", ok: true },
    ],
    num_facture_rapprochee: "FA-26-0117",
    facture_rapprochee: {
      num_facture: "FA-26-0117",
      montant_ttc: "8400.000",
      montant_avoirs: "282.496",
      montant_net: "8117.504",
    },
    montant_avoirs_saisi: null,
    debtor_coverage: {
      total_bills_amount: "8117.504",
      total_invoices_net_amount: "8117.504",
      total_credit_notes_amount: "0.000",
      gap: "0.000",
      sufficient: true,
    },
    control_rollup: {
      mandatory_mentions_ok: true,
      duplicated_fields_ok: true,
      date_rules_ok: true,
      identification_ok: true,
      coverage_ok: true,
    },
    domiciliation: null,
    cross_field_discrepancies: [],
    ...overrides,
  };
}

function renderAnalysisPage(traite: TraiteDetail) {
  mockedApi.getTraite.mockResolvedValue(traite);
  return renderWithProviders(
    <Routes>
      <Route path="/traites/:id" element={<AnalysisPage />} />
    </Routes>,
    { route: "/traites/t1" },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.getTraiteStatus.mockResolvedValue({ statut: "En cours OCR", en_cours: true });
});

describe("AnalysisPage", () => {
  it("renders the summary header and the read-model panels", async () => {
    renderAnalysisPage(baseTraite());

    expect(await screen.findByText("011570763437")).toBeInTheDocument();
    // "ADACTIM" legitimately appears twice — the summary header's Tireur
    // field and the NLP match display — so this asserts presence, not
    // uniqueness.
    expect(screen.getAllByText("ADACTIM").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("LA MÉDITERRANÉENNE").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("FA-26-0117")).toBeInTheDocument();
    expect(screen.getByText("Terminer les vérifications manuelles")).toBeInTheDocument();
  });

  it("shows skeleton cards and a scanning overlay over the real scan while en cours OCR", async () => {
    URL.createObjectURL = vi.fn(() => "blob:mock-url");
    URL.revokeObjectURL = vi.fn();
    mockedApi.getDocumentBlob.mockResolvedValue(new Blob(["fake-bytes"], { type: "image/jpeg" }));

    const traite = baseTraite({
      statut: "En cours OCR",
      documents: [
        { id: "d1", face: "recto", fichier_nom: "recto.jpg", content_type: "image/jpeg", taille_octets: 10, uploaded_at: new Date().toISOString() },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    // Skeleton cards keep the same headers as the real ones (no layout
    // jump once data arrives)...
    expect(screen.getByText("Verdict de l'agent")).toBeInTheDocument();
    expect(screen.getByText("Contrôle de cohérence des champs dupliqués")).toBeInTheDocument();
    // ...but never show real computed content or interactive controls this
    // early — that would let a check be ticked against data that doesn't
    // exist yet.
    expect(screen.queryByText("Terminer les vérifications manuelles")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /conforme/i })).not.toBeInTheDocument();

    // The scanning overlay sits over both the recto AND verso panels —
    // extraction reads both faces in one pass, not one at a time.
    expect(screen.getAllByText(/Lecture du scan/).length).toBe(2);
    await waitFor(() => expect(mockedApi.getDocumentBlob).toHaveBeenCalledWith("t1", "recto"));
  });

  it("renders duplicate-field coherence correctly", async () => {
    renderAnalysisPage(baseTraite());
    await screen.findByText("Échéance");
    expect(screen.getByText("✓ Cohérent")).toBeInTheDocument();
  });

  it("shows Montant en lettres in the duplicated-fields coherence table like any other field", async () => {
    // Reversed from an earlier call to hide it here: once the cross-field
    // discrepancies banner correctly stopped showing plain field names
    // (that banner used to be the only, accidental place montant_lettres'
    // own coherence was visible at all), hiding it from this table too
    // left it with nowhere to appear - found live by the user looking for
    // exactly this row and not finding it anywhere on the page.
    const traite = baseTraite({
      champs_extraits: [
        { id: "c1", nom_champ: "echeance", occurrence: 1, valeur: "2026-08-28", source: "ocr", confiance: null },
        { id: "c2", nom_champ: "echeance", occurrence: 2, valeur: "2026-08-28", source: "ocr", confiance: null },
        { id: "c3", nom_champ: "montant_lettres", occurrence: 1, valeur: "Huit mille cent dix-sept dinars", source: "ocr", confiance: null },
        { id: "c4", nom_champ: "montant_lettres", occurrence: 2, valeur: "Huit mille cent dix-sept dinars", source: "ocr", confiance: null },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("Échéance");
    expect(screen.getByText("Montant en lettres")).toBeInTheDocument();
    expect(screen.getAllByText("Huit mille cent dix-sept dinars").length).toBe(2);
  });

  it("flags Montant en lettres as an écart when its own two occurrences disagree", async () => {
    const traite = baseTraite({
      champs_extraits: [
        { id: "c1", nom_champ: "montant_lettres", occurrence: 1, valeur: "Huit mille cent dix-sept dinars, 504 millimes", source: "ocr", confiance: null },
        { id: "c2", nom_champ: "montant_lettres", occurrence: 2, valeur: null, source: "ocr", confiance: null },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("Montant en lettres");

    const row = screen.getByText("Montant en lettres").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("⚠ Écart")).toBeInTheDocument();
  });

  it("flags an incoherent duplicated field", async () => {
    const traite = baseTraite({
      champs_extraits: [
        { id: "c1", nom_champ: "echeance", occurrence: 1, valeur: "2026-08-28", source: "ocr", confiance: null },
        { id: "c2", nom_champ: "echeance", occurrence: 2, valeur: "2026-09-01", source: "ocr", confiance: null },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("Échéance");
    expect(screen.getByText("⚠ Écart")).toBeInTheDocument();
  });

  it("shows the cross-field discrepancies banner with a human label per code", async () => {
    const traite = baseTraite({
      cross_field_discrepancies: [
        "rib_tire_vs_reconstitution_4_segments",
        "montant_lettres_vs_chiffres",
        "numero_lcn_vs_code_barres",
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    expect(screen.getByText("Écarts croisés détectés")).toBeInTheDocument();
    expect(screen.getByText(/RIB direct ≠ RIB reconstitué depuis les 4 sous-champs/)).toBeInTheDocument();
    expect(screen.getByText(/Montant en lettres ≠ montant en chiffres/)).toBeInTheDocument();
    expect(screen.getByText(/N° L-CN \(OCR\) ≠ N° L-CN \(code-barres\)/)).toBeInTheDocument();
  });

  it("hides the cross-field discrepancies banner when there are none", async () => {
    renderAnalysisPage(baseTraite({ cross_field_discrepancies: [] }));
    await screen.findByText("011570763437");

    expect(screen.queryByText("Écarts croisés détectés")).not.toBeInTheDocument();
  });

  it("never shows a plain field's own occurrence mismatch as a cross-field discrepancy", async () => {
    // Real case found live: montant_chiffres/montant_lettres each missing
    // their 2nd occurrence lands both plain field names in
    // cross_field_discrepancies (compute_inconsistencies' first, per-field
    // check) — but the real montant_lettres_vs_chiffres cross-check never
    // even ran (it requires both fields individually coherent first). The
    // banner must stay hidden here: showing "montant_chiffres" alone falsely
    // implies chiffres and lettres disagree with each other, when they were
    // never actually compared. That per-field mismatch is already visible,
    // correctly, as an "⚠ Écart" row in the coherence table above.
    const traite = baseTraite({ cross_field_discrepancies: ["montant_chiffres", "montant_lettres"] });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    expect(screen.queryByText("Écarts croisés détectés")).not.toBeInTheDocument();
    expect(screen.queryByText(/montant_chiffres/)).not.toBeInTheDocument();
  });

  it("shows the read-only IMX facture context distinct from the cashier's own saisie field", async () => {
    renderAnalysisPage(baseTraite());
    await screen.findByText("011570763437");

    expect(screen.getByText(/Référentiel IMX \(lecture seule\)/)).toBeInTheDocument();
    expect(screen.getByText(/facture FA-26-0117/)).toBeInTheDocument();
    expect(screen.getByLabelText("Avoirs saisis (DT)")).toHaveValue(null);
  });

  it("prefills the avoirs input with an existing saisie", async () => {
    renderAnalysisPage(baseTraite({ montant_avoirs_saisi: "150.500" }));
    await screen.findByText("011570763437");

    expect(screen.getByLabelText("Avoirs saisis (DT)")).toHaveValue(150.5);
  });

  it("saves the cashier's avoirs saisie on blur", async () => {
    mockedApi.updateMontantAvoirs.mockResolvedValue(baseTraite());
    renderAnalysisPage(baseTraite());
    await screen.findByText("011570763437");

    const input = screen.getByLabelText("Avoirs saisis (DT)");
    await userEvent.type(input, "150.5");
    await userEvent.tab();

    expect(mockedApi.updateMontantAvoirs).toHaveBeenCalledWith("t1", 150.5);
  });

  it("clears a previous saisie by blurring an empty avoirs input", async () => {
    mockedApi.updateMontantAvoirs.mockResolvedValue(baseTraite());
    renderAnalysisPage(baseTraite({ montant_avoirs_saisi: "150.500" }));
    await screen.findByText("011570763437");

    const input = screen.getByLabelText("Avoirs saisis (DT)");
    await userEvent.clear(input);
    await userEvent.tab();

    expect(mockedApi.updateMontantAvoirs).toHaveBeenCalledWith("t1", null);
  });

  it("shows a sufficient-coverage badge with the aggregated totals", async () => {
    renderAnalysisPage(baseTraite());
    await screen.findByText("011570763437");

    expect(screen.getByText("Couverture suffisante")).toBeInTheDocument();
    expect(screen.getByText(/Traites 8 117,504 DT/)).toBeInTheDocument();
  });

  it("shows an insufficient-coverage badge when the gap exceeds the threshold", async () => {
    const traite = baseTraite({
      debtor_coverage: {
        total_bills_amount: "8117.504",
        total_invoices_net_amount: "500.000",
        total_credit_notes_amount: "0.000",
        gap: "-7617.504",
        sufficient: false,
      },
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    expect(screen.getByText("Couverture insuffisante")).toBeInTheDocument();
  });

  it("hides the coverage summary when the debtor isn't resolved yet", async () => {
    const traite = baseTraite({ debtor_coverage: null });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    expect(screen.queryByText(/Couverture facture\/IP du débiteur/)).not.toBeInTheDocument();
  });

  describe("Valider button", () => {
    it("is disabled when the backend's own bloque flag is true, even with a title explaining why", async () => {
      renderAnalysisPage(baseTraite({ bloque: true, motif_blocage: "Écarts automatiques non résolus (OCR/NLP)" }));
      await screen.findByText("011570763437");

      const button = screen.getByRole("button", { name: "✓ Valider" });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Écarts automatiques non résolus (OCR/NLP)");
    });

    it("calls createDecision(type=validee) and shows a success toast when clicked while unblocked", async () => {
      mockedApi.createDecision.mockResolvedValue({
        id: "d1",
        type: "validee",
        commentaire: null,
        decide_par: "h.mansouri",
        decide_le: new Date().toISOString(),
      });
      renderAnalysisPage(baseTraite({ bloque: false, recommandation: { titre: "Valider la traite", detail: "Tous les contrôles automatiques et manuels sont levés." } }));
      await screen.findByText("011570763437");

      const button = screen.getByRole("button", { name: "✓ Valider" });
      expect(button).toBeEnabled();
      await userEvent.click(button);

      expect(mockedApi.createDecision).toHaveBeenCalledWith("t1", "validee");
      expect(await screen.findByText("Traite validée")).toBeInTheDocument();
    });

    it("hides the button and shows the final-decision message once the traite already has a decision", async () => {
      renderAnalysisPage(
        baseTraite({
          bloque: false,
          decisions: [
            { id: "d1", type: "validee", commentaire: null, decide_par: "h.mansouri", decide_le: new Date().toISOString() },
          ],
        })
      );
      await screen.findByText("011570763437");

      expect(screen.queryByRole("button", { name: "✓ Valider" })).not.toBeInTheDocument();
      expect(screen.getByText("Décision déjà enregistrée")).toBeInTheDocument();
    });

    it("shows an error toast and never claims success when the backend rejects validation", async () => {
      mockedApi.createDecision.mockRejectedValue(new ApiError(409, "Écarts automatiques non résolus (OCR/NLP)"));
      renderAnalysisPage(baseTraite({ bloque: false }));
      await screen.findByText("011570763437");

      await userEvent.click(screen.getByRole("button", { name: "✓ Valider" }));

      expect(await screen.findByText("Validation impossible")).toBeInTheDocument();
      expect(screen.queryByText("Traite validée")).not.toBeInTheDocument();
    });
  });

  it("calls updateVerification when a check button is clicked", async () => {
    mockedApi.updateVerification.mockResolvedValue(baseTraite());
    renderAnalysisPage(baseTraite());
    await screen.findByText("011570763437");

    const conformeButtons = screen.getAllByRole("button", { name: /conforme/i });
    await userEvent.click(conformeButtons[0]);

    expect(mockedApi.updateVerification).toHaveBeenCalledWith("t1", "sigTire", "conforme");
  });

  it("fetches the document as an authenticated blob and renders it as an image", async () => {
    URL.createObjectURL = vi.fn(() => "blob:mock-url");
    URL.revokeObjectURL = vi.fn();
    mockedApi.getDocumentBlob.mockResolvedValue(new Blob(["fake-bytes"], { type: "image/png" }));

    const traite = baseTraite({
      documents: [
        { id: "d1", face: "recto", fichier_nom: "recto.png", content_type: "image/png", taille_octets: 10, uploaded_at: new Date().toISOString() },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    await waitFor(() => expect(mockedApi.getDocumentBlob).toHaveBeenCalledWith("t1", "recto"));
    const image = await screen.findByAltText("recto de la traite");
    expect(image).toHaveAttribute("src", "blob:mock-url");
  });

  it("shows how each NLP match was identified — via RIB vs name-only", async () => {
    const traite = baseTraite({
      rapprochements_nlp: [
        {
          id: "n1",
          role: "tire",
          valeur_scan: "LA MÉDITERRANÉENNE",
          valeur_referentiel: "LA MÉDITERRANÉENNE",
          score: "97.00",
          code_adherent_matche: null,
          code_debiteur_matche: "DEB-1001",
          methode_identification: "rib",
          alerte_ecart_nom: false,
        },
        {
          id: "n2",
          role: "tireur",
          valeur_scan: "ADACTIM",
          valeur_referentiel: "ADACTIM",
          score: "100.00",
          code_adherent_matche: "ADH-1001",
          code_debiteur_matche: null,
          methode_identification: "nom_seul",
          alerte_ecart_nom: false,
        },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    expect(screen.getByText("Identifié par RIB")).toBeInTheDocument();
    expect(screen.getByText("Nom seul — à confirmer")).toBeInTheDocument();
  });

  it("shows a dedicated RIB row without a redundant méthode badge under itself", async () => {
    const traite = baseTraite({
      rapprochements_nlp: [
        {
          id: "n1",
          role: "rib",
          valeur_scan: "11003000291700178836",
          valeur_referentiel: "11003000291700178836",
          score: "100.00",
          code_adherent_matche: null,
          code_debiteur_matche: "DEB-1001",
          methode_identification: "rib",
          alerte_ecart_nom: false,
        },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    // Appears twice: once as the scanned value, once as the matched
    // référentiel value (a real RIB match shows the same digits both
    // sides).
    expect(screen.getAllByText("11003000291700178836")).toHaveLength(2);
    // The RIB row's own 100% score already says this — no separate
    // "Identifié par RIB" badge repeating it under the row itself.
    expect(screen.queryByText("Identifié par RIB")).not.toBeInTheDocument();
  });

  it("shows the domiciliation text under the RIB row when the model returns one", async () => {
    const traite = baseTraite({
      rapprochements_nlp: [
        {
          id: "n1",
          role: "rib",
          valeur_scan: "11003000291700178836",
          valeur_referentiel: "11003000291700178836",
          score: "100.00",
          code_adherent_matche: null,
          code_debiteur_matche: "DEB-1001",
          methode_identification: "rib",
          alerte_ecart_nom: false,
        },
      ],
      domiciliation: "UBCI Agence Paris, Tunis",
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    expect(screen.getByText("UBCI Agence Paris, Tunis")).toBeInTheDocument();
  });

  it("shows no domiciliation line when the model didn't return one", async () => {
    const traite = baseTraite({
      rapprochements_nlp: [
        {
          id: "n1",
          role: "rib",
          valeur_scan: "11003000291700178836",
          valeur_referentiel: "11003000291700178836",
          score: "100.00",
          code_adherent_matche: null,
          code_debiteur_matche: "DEB-1001",
          methode_identification: "rib",
          alerte_ecart_nom: false,
        },
      ],
      domiciliation: null,
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    expect(screen.queryByText(/Domiciliation/)).not.toBeInTheDocument();
  });

  it("flags a RIB-confirmed débiteur whose scanned name doesn't corroborate", async () => {
    const traite = baseTraite({
      rapprochements_nlp: [
        {
          id: "n1",
          role: "tire",
          valeur_scan: "SPG",
          valeur_referentiel: "LA MÉDITERRANÉENNE",
          score: "12.00",
          code_adherent_matche: null,
          code_debiteur_matche: "DEB-1001",
          methode_identification: "rib",
          alerte_ecart_nom: true,
        },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    expect(screen.getByText(/RIB confirmé mais nom incohérent/)).toBeInTheDocument();
  });

  it("shows recto and verso stacked, always both visible, with no face-switching tab", async () => {
    URL.createObjectURL = vi.fn(() => "blob:mock-url");
    URL.revokeObjectURL = vi.fn();
    mockedApi.getDocumentBlob.mockResolvedValue(new Blob(["fake-bytes"], { type: "image/jpeg" }));

    const traite = baseTraite({
      documents: [
        { id: "d1", face: "recto", fichier_nom: "recto.jpg", content_type: "image/jpeg", taille_octets: 10, uploaded_at: new Date().toISOString() },
        { id: "d2", face: "verso", fichier_nom: "verso.jpg", content_type: "image/jpeg", taille_octets: 10, uploaded_at: new Date().toISOString() },
      ],
    });
    renderAnalysisPage(traite);
    await screen.findByText("011570763437");

    await waitFor(() => expect(mockedApi.getDocumentBlob).toHaveBeenCalledWith("t1", "recto"));
    await waitFor(() => expect(mockedApi.getDocumentBlob).toHaveBeenCalledWith("t1", "verso"));
    // Both render unconditionally, stacked — no tab/toggle needed to switch
    // between them (there's nothing left to click to reveal the other one).
    expect(await screen.findByAltText("recto de la traite")).toBeInTheDocument();
    expect(await screen.findByAltText("verso de la traite")).toBeInTheDocument();
  });
});
