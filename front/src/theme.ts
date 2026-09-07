/**
 * Design tokens extracted verbatim from the TRAIT-AI mockup (TRAIT-AI/index.html).
 * Every value here is a literal copy of a color already used and validated in
 * the design — this file exists to avoid repeating hex strings across dozens
 * of components, not to introduce any new visual choice.
 */
export const colors = {
  navy900: "#0B2239",
  navyHover: "#14395C",
  blue700: "#1E5C8F",
  blueBg: "#E8F0F8",
  blueBorder: "#C6DAEC",
  blueText: "#14507F",

  bgPage: "#EEF1F5",
  bgCard: "#FFFFFF",
  bgChip: "#F3F6F9",
  bgHover: "#F5F7FA",
  bgSubtle: "#F7F9FB",

  textPrimary: "#16222E",
  textSecondary: "#3C4E5F",
  textMuted: "#6B7E90",
  textHeading: "#2A3B4C",

  border: "#D7DEE7",
  borderInput: "#DCE3EA",
  divider: "#E4E9EF",
  dividerLight: "#EDF1F5",
  dividerTopbar: "#E1E7ED",

  green: "#1E7A4B",
  greenBg: "#E8F4ED",
  greenBorder: "#C2E0CE",
  greenText: "#155F3A",

  orange: "#B3600A",
  orangeBg: "#FDF1E2",
  orangeBorder: "#EFD6B4",
  orangeText: "#7A4306",

  purple: "#7A4FB3",
  purpleBg: "#F6F2FB",
  purpleBgAlt: "#F3EDFB",
  purpleBorder: "#DCCCF0",
  purpleBorderAlt: "#E4D9F2",
  purpleText: "#5E3A8C",
  purpleTextDark: "#3F2A5E",

  red: "#B3261E",
  redBg: "#FBEAE8",
  redBorder: "#ECC3BF",
  redText: "#8E3A33",
  redTextDark: "#7E2A24",
} as const;

export const fonts = {
  sans: "'IBM Plex Sans',system-ui,sans-serif",
  mono: "'IBM Plex Mono',monospace",
} as const;

/** Status → badge colors, mirrors the mockup's STATUS map exactly. */
export const statusColors: Record<string, { fg: string; bg: string; border: string }> = {
  "À traiter": { fg: colors.textSecondary, bg: colors.bgPage, border: colors.border },
  "En cours OCR": { fg: colors.blueText, bg: colors.blueBg, border: colors.blueBorder },
  "Écarts à traiter": { fg: colors.orangeText, bg: colors.orangeBg, border: colors.orangeBorder },
  "Contrôle manuel requis": { fg: colors.purpleText, bg: colors.purpleBgAlt, border: colors.purpleBorder },
  "Renvoyée": { fg: colors.orangeText, bg: colors.orangeBg, border: colors.orangeBorder },
  "Fraude signalée": { fg: colors.redText, bg: colors.redBg, border: colors.redBorder },
  "Validée": { fg: colors.greenText, bg: colors.greenBg, border: colors.greenBorder },
};
