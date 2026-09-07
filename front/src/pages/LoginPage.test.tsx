import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
import { ApiError } from "../api/client";
import { renderWithProviders } from "../test/test-utils";
import LoginPage from "./LoginPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, login: vi.fn() };
});

const mockedApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

function LoginWithRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<div>Queue placeholder</div>} />
    </Routes>
  );
}

describe("LoginPage", () => {
  it("shows an error toast when submitting without credentials", async () => {
    renderWithProviders(<LoginWithRoutes />, { route: "/login" });

    await userEvent.click(screen.getByRole("button", { name: /se connecter/i }));

    expect(await screen.findByText(/connexion refusée/i)).toBeInTheDocument();
  });

  it("logs in and navigates to the queue on valid submit", async () => {
    mockedApi.login.mockResolvedValue({ access_token: "tok", token_type: "bearer", username: "h.mansouri" });
    renderWithProviders(<LoginWithRoutes />, { route: "/login" });

    await userEvent.type(screen.getByPlaceholderText("h.mansouri"), "h.mansouri");
    await userEvent.type(screen.getByPlaceholderText("••••••••"), "secret123");
    await userEvent.click(screen.getByRole("button", { name: /se connecter/i }));

    await waitFor(() => expect(screen.getByText("Queue placeholder")).toBeInTheDocument());
  });

  it("shows an error toast and stays on the page when the LDAP bind is rejected", async () => {
    mockedApi.login.mockRejectedValue(new ApiError(401, "Identifiant ou mot de passe incorrect."));
    renderWithProviders(<LoginWithRoutes />, { route: "/login" });

    await userEvent.type(screen.getByPlaceholderText("h.mansouri"), "h.mansouri");
    await userEvent.type(screen.getByPlaceholderText("••••••••"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /se connecter/i }));

    expect(await screen.findByText(/connexion refusée/i)).toBeInTheDocument();
    expect(screen.queryByText("Queue placeholder")).not.toBeInTheDocument();
  });

  it("has no role picker (removed from the design)", () => {
    renderWithProviders(<LoginWithRoutes />, { route: "/login" });
    expect(screen.queryByText(/profil/i)).not.toBeInTheDocument();
  });
});
