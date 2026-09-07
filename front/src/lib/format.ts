/** French-locale formatting matching the design's exact conventions
 * (space thousands separator, comma decimal, 3-decimal dinars/millimes).
 *
 * toLocaleString("fr-FR") inserts U+202F (narrow no-break space) as the
 * thousands separator, not a plain space -- correct French typography, but
 * it doesn't byte-match the mockup's own literal text and its rendering
 * can vary across ICU versions. Normalized to a plain ASCII space using
 * String.fromCharCode, deliberately avoiding any literal whitespace-like
 * character in this source file, so the output is deterministic and
 * portable regardless of how this file's bytes get transmitted/edited. */
const NARROW_NO_BREAK_SPACE = String.fromCharCode(0x202f);
const REGULAR_SPACE = String.fromCharCode(0x20);

export function formatMontant(montant: string): string {
  const value = Number(montant);
  const formatted = value
    .toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 })
    .split(NARROW_NO_BREAK_SPACE)
    .join(REGULAR_SPACE);
  return formatted + REGULAR_SPACE + "DT";
}

export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}/${month}/${year}`;
}

export function formatDateTime(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = String(date.getFullYear()).slice(-2);
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${day}/${month}/${year} ${hours}:${minutes}`;
}

const SLA_HOURS = 24;

export interface SlaState {
  label: string;
  percent: number;
  color: string;
}

/**
 * Derived entirely from the real date_reception timestamp against a 24h
 * processing SLA -- this is the design's own "Delai (SLA 24h)" column, not
 * a stored field. Computed at render time (not live-ticking) -- a
 * setInterval-driven countdown is a reasonable future enhancement, not in
 * this sprint's scope.
 */
export function computeSla(dateReception: string, statut: string): SlaState {
  if (statut === "Validée") {
    return { label: "Clôturée", percent: 100, color: "#1E7A4B" };
  }

  const received = new Date(dateReception).getTime();
  const now = Date.now();
  const elapsedHours = (now - received) / (1000 * 60 * 60);
  const remainingHours = SLA_HOURS - elapsedHours;
  const percent = Math.min(100, Math.max(0, (elapsedHours / SLA_HOURS) * 100));

  if (remainingHours <= 0) {
    return { label: "Délai dépassé", percent: 100, color: "#B3261E" };
  }

  const hours = Math.floor(remainingHours);
  const minutes = Math.round((remainingHours - hours) * 60);
  const label = `${hours}h ${String(minutes).padStart(2, "0")}m restantes`;
  const color = percent >= 85 ? "#B3261E" : percent >= 50 ? "#B3600A" : "#1E5C8F";
  return { label, percent, color };
}
