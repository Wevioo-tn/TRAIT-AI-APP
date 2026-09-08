import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
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

  it("hides Montant en lettres from the duplicated-fields coherence table", async () => {
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
    expect(screen.queryByText("Montant en lettres")).not.toBeInTheDocument();
    expect(screen.queryByText("Huit mille cent dix-sept dinars")).not.toBeInTheDocument();
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
