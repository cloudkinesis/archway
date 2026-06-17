import { ShieldCheck } from "lucide-react";

import type { ExportBundle } from "../lib/types";

/**
 * Read-only Trust & Reproducibility panel.
 *
 * Renders ONLY backend/export/manifest/pricing-metadata state. It invents no trust
 * signal: every badge maps to a field already present in the pricing metadata or the
 * export bundle's artifact list. Global readiness is never promoted, and a green
 * procurement-ready label requires BOTH rate authority and quantity confirmation.
 */

type PricingLike = {
  low_monthly_usd?: number | string;
  expected_monthly_usd?: number | string;
  high_monthly_usd?: number | string;
  region?: string;
  metadata?: Record<string, unknown> | null;
};

type PilotTrace = {
  status?: string;
  sku_backed_subtotal?: string;
  rate_authoritative?: boolean;
  quantities_confirmed?: boolean;
  quantity_source?: string;
  sku_pilot_estimate_ready?: boolean;
  sku_pilot_procurement_ready?: boolean;
  snapshot_id?: string;
  snapshot_source?: string;
  source_hash?: string;
  upstream_source?: string;
  version_hash?: string;
  estimate_input_hash?: string;
  not_estimated?: string[];
};

type SourceTruthPricingTrace = {
  mode?: string;
  status?: string;
};

function shortHash(value?: string): string {
  if (!value) return "—";
  return value.replace("sha256:", "").slice(0, 12);
}

function Badge({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "bad" | "neutral" }) {
  const palette: Record<string, string> = {
    good: "border-green-600 text-green-700 bg-green-50",
    warn: "border-amber-500 text-amber-700 bg-amber-50",
    bad: "border-red-500 text-red-700 bg-red-50",
    neutral: "border-awsBorder text-awsTextSecondary bg-white",
  };
  return (
    <span className={`inline-flex items-center gap-1 border px-2 py-1 text-xs ${palette[tone]}`}>
      <span className="font-semibold uppercase tracking-wide">{label}:</span> {value}
    </span>
  );
}

export function TrustPanel({
  pricing,
  exportBundle,
  verification,
}: {
  pricing: PricingLike;
  exportBundle: ExportBundle | null;
  // Result of actually running scripts/verify_solution_dossier.py, when available.
  // The UI does not run the verifier itself, so this is normally absent.
  verification?: { verified: boolean } | null;
}) {
  const metadata = pricing.metadata ?? {};
  const headlineSafe = metadata.pricing_can_be_displayed_as_headline !== false;
  const sourceTruth = (metadata.source_truth_pricing_compiler as SourceTruthPricingTrace | undefined) ?? undefined;
  const pricingMaturity = String(metadata.pricing_maturity ?? "").toLowerCase();
  const pricingStatus = String(metadata.status ?? metadata.pricing_status ?? "").toLowerCase();
  const headlineBlocked =
    !headlineSafe ||
    sourceTruth?.mode === "generic_not_estimated" ||
    sourceTruth?.status === "generic_not_estimated" ||
    pricingMaturity.includes("not_estimated") ||
    pricingStatus.includes("invalid");
  const pilot = (metadata.sku_pricing_pilot as PilotTrace | undefined) ?? undefined;

  const artifacts = exportBundle?.included_artifacts ?? [];
  const hasExport = exportBundle != null;
  const manifestPresent = artifacts.some((a) => a.endsWith("dossier_manifest.json"));
  const skuTracePresent = artifacts.some((a) => a.endsWith("sku_pricing_pilot_trace.json"));

  // Verification is NOT inferred from manifest presence. "verified" is shown only when
  // an actual verifier result is supplied; otherwise we report that it can be run offline.
  const verificationLabel = verification
    ? (verification.verified ? "verified" : "failed")
    : manifestPresent ? "not run — available offline" : "not run";
  const verificationTone: "good" | "warn" | "bad" | "neutral" = verification
    ? (verification.verified ? "good" : "bad")
    : "neutral";

  const rateAuthoritative = pilot?.rate_authoritative === true;
  const quantitiesConfirmed = pilot?.quantities_confirmed === true;
  const procurementReady = Boolean(pilot?.sku_pilot_procurement_ready) && rateAuthoritative && quantitiesConfirmed;

  const pricingMode = pilot ? (headlineSafe ? "Mixed (legacy + SKU pilot)" : "SKU-backed pilot") : "Directional";
  const eventbridgeNote = (pilot?.not_estimated ?? []).some((entry) => entry.toLowerCase().includes("eventbridge"));
  const knownGaps = (pilot?.not_estimated?.length ?? 0) + (exportBundle?.warnings?.length ?? 0);

  return (
    <div className="border border-awsBorder bg-surface p-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-5 w-5 text-awsOrange" />
        <h3 className="text-base font-semibold">Trust &amp; Reproducibility</h3>
      </div>
      <p className="mt-1 text-xs text-awsTextMuted">
        Derived only from the pricing metadata and the export package manifest. No trust state is inferred.
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        <Badge label="Dossier manifest" value={hasExport ? (manifestPresent ? "present" : "missing") : "not generated"}
               tone={hasExport ? (manifestPresent ? "good" : "bad") : "neutral"} />
        <Badge label="Verification" value={verificationLabel} tone={verificationTone} />
        <Badge label="Pricing mode" value={pricingMode} tone={pilot ? "warn" : "neutral"} />
        {pilot ? <Badge label="Rate authoritative" value={rateAuthoritative ? "yes" : "no"} tone={rateAuthoritative ? "good" : "bad"} /> : null}
        {pilot ? <Badge label="Quantities confirmed" value={quantitiesConfirmed ? "yes" : "no"} tone={quantitiesConfirmed ? "good" : "warn"} /> : null}
        <Badge label="Procurement-ready" value={procurementReady ? "yes" : "no"} tone={procurementReady ? "good" : "bad"} />
        {pilot ? <Badge label="Supplemental only" value="yes" tone="neutral" /> : null}
        <Badge label="Known gaps" value={String(knownGaps)} tone={knownGaps > 0 ? "warn" : "neutral"} />
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {/* Legacy estimate */}
        <div className="border border-awsBorder bg-white p-3 text-sm">
          <div className="font-semibold">Legacy estimate</div>
          {headlineBlocked ? (
            <div className="mt-2 border border-awsWarning/50 bg-[#fff8e5] p-2 text-awsTextSecondary">
              Budget-grade pricing is not available yet. Numeric placeholders are held from headline display until pricing drivers and quantity bindings are safe.
            </div>
          ) : (
            <div className="mt-2 text-awsTextSecondary">
              Range ${String(pricing.low_monthly_usd ?? "—")}–${String(pricing.high_monthly_usd ?? "—")} · Expected ${String(pricing.expected_monthly_usd ?? "—")}
            </div>
          )}
          <div className="mt-1 text-xs text-awsTextMuted">Headline-safe: {headlineSafe ? "yes" : "no"}</div>
          <div className="mt-1 text-xs text-awsTextMuted">
            {headlineBlocked ? "Top-line range is hidden from this panel until pricing is safe to present." : "Directional unless AWS pricing evidence is bound."}
          </div>
        </div>

        {/* SKU-backed pilot */}
        {pilot ? (
          <div className="border border-awsBorder bg-white p-3 text-sm">
            <div className="font-semibold">SKU-backed pilot</div>
            <div className="mt-1 text-xs font-semibold text-awsOrange">Supplemental SKU-backed pilot trace</div>
            <div className="text-xs text-awsTextMuted">Does not replace the legacy estimate.</div>
            <dl className="mt-2 space-y-1 text-xs text-awsTextSecondary">
              <div>Subtotal: ${String(pilot.sku_backed_subtotal ?? "—")}</div>
              <div>Snapshot: {pilot.snapshot_id ?? "—"} ({pilot.snapshot_source ?? "—"})</div>
              <div>Upstream source: {pilot.upstream_source ?? "—"}</div>
              <div>Source hash: {shortHash(pilot.source_hash)} · Version hash: {shortHash(pilot.version_hash)}</div>
              <div>Estimate input hash: {shortHash(pilot.estimate_input_hash)}</div>
              <div>Rate authoritative: {rateAuthoritative ? "yes" : "no"} · Quantities confirmed: {quantitiesConfirmed ? "yes" : "no"} ({pilot.quantity_source ?? "—"})</div>
            </dl>
            {rateAuthoritative && !quantitiesConfirmed ? (
              <div className="mt-2 border-l-2 border-amber-500 pl-2 text-xs text-amber-700">
                Not procurement-ready while quantities are assumed.
              </div>
            ) : null}
            {!rateAuthoritative ? (
              <div className="mt-2 border-l-2 border-red-500 pl-2 text-xs text-red-700">
                Rates are not authoritative — not a procurement estimate.
              </div>
            ) : null}
            {(pilot.not_estimated?.length ?? 0) > 0 ? (
              <div className="mt-2 text-xs text-awsTextMuted">
                Not estimated: {pilot.not_estimated!.join(", ")}
              </div>
            ) : null}
            {eventbridgeNote ? (
              <div className="mt-2 text-xs text-awsTextMuted">EventBridge not estimated: AWS bills 64KB chunks.</div>
            ) : null}
            {skuTracePresent ? (
              <div className="mt-2 text-xs text-awsTextMuted">Trace files: pricing/sku_pricing_pilot_trace.json · .csv · summary.md</div>
            ) : null}
          </div>
        ) : (
          <div className="border border-dashed border-awsBorder bg-white p-3 text-xs text-awsTextMuted">
            No SKU-backed pilot trace present (flag off, non-document-RAG workload, or no authoritative snapshot).
          </div>
        )}
      </div>
    </div>
  );
}
