import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
import type { TraiteCountsRead, TraiteDetail, TraitePage } from "../api/types";
import { renderWithProviders } from "../test/test-utils";
import QueuePage from "./QueuePage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    listTraites: vi.fn(),
    getTraiteCounts: vi.fn(),
    createTraite: vi.fn(),
    uploadDocument: vi.fn(),
    lancerAnalyse: vi.fn(),
  };
});

const mockedApi = vi.mocked(api);

const EMPTY_COUNTS: TraiteCountsRead = {
  par_statut: {
    "À traiter": 1,
    "En cours OCR": 0,
    "Écarts à traiter": 0,
    "Contrôle manuel requis": 0,
    "Renvoyée": 0,
    "Fraude signalée": 0,
    "Validée": 0,
  },
};

const ONE_TRAITE_PAGE: TraitePage = {
  items: [
    {
      id: "t1",
      numero_lcn: "011570763437",
      montant: "8117.504",
      date_echeance: "2026-08-28",
      date_creation_traite: "2026-08-05",
      date_reception: new Date().toISOString(),
      statut: "À traiter",
      code_adherent: null,
      code_debiteur: null,
      tireur_nom: null,
      tire_nom: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ],
  total: 1,
  page: 1,
  per_page: 6,
};

function QueueWithRoutes() {
  return (
    <Routes>
      <Route path="/" element={<QueuePage />} />
      <Route path="/traites/:id" element={<div>Analysis page placeholder</div>} />
    </Routes>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.listTraites.mockResolvedValue(ONE_TRAITE_PAGE);
  mockedApi.getTraiteCounts.mockResolvedValue(EMPTY_COUNTS);
});

describe("QueuePage", () => {
  it("renders the fetched traite in the table", async () => {
    renderWithProviders(<QueuePage />);
    expect(await screen.findByText("011570763437")).toBeInTheDocument();
    expect(screen.getByText("8 117,504 DT")).toBeInTheDocument();
  });

  it("shows a dash for tireur/tiré before NLP resolution instead of a blank cell", async () => {
    renderWithProviders(<QueuePage />);
    await screen.findByText("011570763437");
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("disables the launch button until both recto and verso are provided", async () => {
    renderWithProviders(<QueuePage />);
    await screen.findByText("011570763437");
    expect(screen.getByRole("button", { name: /lancer l'analyse/i })).toBeDisabled();
  });

  it("carries the responsive classes ported from the validated design CSS", async () => {
    const { container } = renderWithProviders(<QueuePage />);
    await screen.findByText("011570763437");
    expect(container.querySelector(".tp-counters")).not.toBeNull();
    expect(container.querySelector(".tp-table-scroll")).not.toBeNull();
    expect(container.querySelector(".tp-dropzone-row")).not.toBeNull();
    expect(container.querySelector(".tp-datatable")).not.toBeNull();
  });

  it("redirects to the analysis page once the launch succeeds", async () => {
    const createdTraite = { id: "new-t1", numero_lcn: "AUTO-TEST01" } as unknown as TraiteDetail;
    mockedApi.createTraite.mockResolvedValue(createdTraite);
    mockedApi.uploadDocument.mockResolvedValue({} as never);
    mockedApi.lancerAnalyse.mockResolvedValue({} as never);

    const { container } = renderWithProviders(<QueueWithRoutes />, { route: "/" });
    await screen.findByText("011570763437");

    const fileInputs = container.querySelectorAll<HTMLInputElement>('input[type="file"]');
    await userEvent.upload(fileInputs[0], new File(["recto"], "recto.jpg", { type: "image/jpeg" }));
    await userEvent.upload(fileInputs[1], new File(["verso"], "verso.jpg", { type: "image/jpeg" }));

    await userEvent.click(screen.getByRole("button", { name: /lancer l'analyse/i }));

    await waitFor(() => expect(screen.getByText("Analysis page placeholder")).toBeInTheDocument());
    expect(mockedApi.uploadDocument).toHaveBeenCalledWith("new-t1", "recto", expect.any(File));
    expect(mockedApi.uploadDocument).toHaveBeenCalledWith("new-t1", "verso", expect.any(File));
    expect(mockedApi.lancerAnalyse).toHaveBeenCalledWith("new-t1");
  });
});
