import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../test/test-utils";
import Topbar from "./Topbar";

describe("Topbar", () => {
  it("hides the logout link until the profile is opened", async () => {
    renderWithProviders(<Topbar pageTitle="Traites à contrôler" />);

    expect(screen.queryByText("Déconnexion")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Utilisateur"));

    expect(screen.getByText("Déconnexion")).toBeInTheDocument();
  });

  it("closes the dropdown again when toggled a second time", async () => {
    renderWithProviders(<Topbar pageTitle="Traites à contrôler" />);

    const trigger = screen.getByText("Utilisateur");
    await userEvent.click(trigger);
    expect(screen.getByText("Déconnexion")).toBeInTheDocument();

    await userEvent.click(trigger);
    expect(screen.queryByText("Déconnexion")).not.toBeInTheDocument();
  });

  it("renders the page title passed in", () => {
    renderWithProviders(<Topbar pageTitle="Analyse OCR / NLP" />);
    expect(screen.getByText("Analyse OCR / NLP")).toBeInTheDocument();
  });
});
