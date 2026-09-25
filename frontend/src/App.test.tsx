import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App, DiffViewer } from "./App";

afterEach(() => vi.restoreAllMocks());

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderApp(path = "/runs") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("IncidentLab frontend", () => {
  it("renders durable run state from the API", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/scenarios")) return jsonResponse([]);
      if (url.endsWith("/api/runs")) {
        return jsonResponse([
          {
            schema_version: 1,
            id: "11111111-1111-1111-1111-111111111111",
            scenario_id: "pool-exhaustion",
            scenario_version: 1,
            pinned_commit: "a".repeat(40),
            workflow_id: "incidentlab-run-1",
            state: "AWAITING_REPAIR_APPROVAL",
            created_at: "2026-09-25T05:00:00Z",
            updated_at: "2026-09-25T05:01:00Z",
          },
        ]);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    renderApp();
    expect(await screen.findByText("Pool exhaustion")).toBeInTheDocument();
    expect(screen.getAllByText("Awaiting approval").length).toBeGreaterThan(0);
  });

  it("renders model-provided diff text without interpreting markup", () => {
    render(<DiffViewer diff={'diff --git a/x b/x\n+<script>alert("x")</script>\n'} />);
    expect(screen.getByText('+<script>alert("x")</script>')).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });
});
