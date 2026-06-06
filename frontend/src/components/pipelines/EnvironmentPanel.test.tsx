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

  it("loads installed packages after connecting with a token", async () => {
    mocked.listPackages.mockResolvedValue({
      installed: [{ name: "labUtils", version: "1.0.0" }],
      history: [],
    });

    render(<EnvironmentPanel />);
    fireEvent.change(screen.getByLabelText("Admin token"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(mocked.listPackages).toHaveBeenCalledWith("secret"));
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
    fireEvent.change(screen.getByLabelText("Admin token"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await screen.findByText("Install a package");

    fireEvent.change(screen.getByLabelText("Package spec"), { target: { value: "labUtils" } });
    fireEvent.click(screen.getByRole("button", { name: "Install" }));

    await waitFor(() => expect(mocked.installPackage).toHaveBeenCalledWith("secret", "labUtils", "pypi"));
    expect(mocked.listPackages).toHaveBeenCalledTimes(2); // connect + refresh after install
  });

  it("surfaces an auth error from the server", async () => {
    mocked.listPackages.mockRejectedValue(new Error("Invalid or missing admin token"));

    render(<EnvironmentPanel />);
    fireEvent.change(screen.getByLabelText("Admin token"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByText("Invalid or missing admin token")).toBeInTheDocument();
  });
});
