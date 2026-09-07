import { describe, expect, it } from "vitest";

import { computeSla, formatDate, formatMontant } from "./format";

describe("formatMontant", () => {
  it("matches the design's exact French formatting", () => {
    expect(formatMontant("8117.504")).toBe("8 117,504 DT");
  });

  it("pads to 3 decimals even for round amounts", () => {
    expect(formatMontant("500")).toBe("500,000 DT");
  });
});

describe("formatDate", () => {
  it("converts ISO to DD/MM/YYYY", () => {
    expect(formatDate("2026-08-28")).toBe("28/08/2026");
  });
});

describe("computeSla", () => {
  it("reports a validated traite as closed regardless of timing", () => {
    const result = computeSla(new Date().toISOString(), "Validée");
    expect(result.label).toBe("Clôturée");
    expect(result.percent).toBe(100);
  });

  it("reports an overdue traite once past the 24h SLA", () => {
    const oneDayAgo = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
    const result = computeSla(oneDayAgo, "À traiter");
    expect(result.label).toBe("Délai dépassé");
  });

  it("reports remaining time for a fresh traite", () => {
    const justNow = new Date().toISOString();
    const result = computeSla(justNow, "À traiter");
    expect(result.label).toMatch(/restantes/);
    expect(result.percent).toBeLessThan(5);
  });
});
