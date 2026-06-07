import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import EnvironmentPanel from "./EnvironmentPanel";
import * as api from "@/lib/api";

vi.mock("@/lib/api");

const mocked = vi.mocked(api);

describe("EnvironmentPanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads installed packages for the signed-in admin", async () => {
    mocked.listPackages.mockResolvedValue({
      installed: [{ name: "labUtils", version: "1.0.0" }],
      history: [],
    });

    render(<EnvironmentPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Load packages" }));

    await waitFor(() => expect(mocked.listPackages).toHaveBeenCalledWith());
    expect(await screen.findByText("labUtils")).toBeInTheDocument();
  });

  it("installs a package and refreshes the list", async () => {
    mocked.listPackages.mockResolvedValue({ installed: [], history: [] });
    mocked.installPackage.mockResolvedValue({
      id: "1",
      action: "install",
      spec: "labUtils",
      source_type: "git",
      resolved_version: "1.0.0",
      exit_code: 0,
      ok: true,
      stdout: "",
      stderr: "",
      actor: "api",
      created_at: "now",
    });

    render(<EnvironmentPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Load packages" }));
    await screen.findByText("Install a package");

    fireEvent.change(screen.getByLabelText("Package spec"), { target: { value: "labUtils" } });
    fireEvent.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() => expect(mocked.installPackage).toHaveBeenCalledWith("labUtils", "pypi"));
    expect(mocked.listPackages).toHaveBeenCalledTimes(2); // initial load + refresh after install
  });

  it("surfaces an authorization error from the server", async () => {
    mocked.listPackages.mockRejectedValue(new Error("Admin role required"));

    render(<EnvironmentPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Load packages" }));

    expect(await screen.findByText("Admin role required")).toBeInTheDocument();
  });
});
