# TRAIT-AI-APP — Todo / Deferred Decisions

Running list of things deliberately **not** being built right now, with the
reasoning behind deferring them — so a future session (or a future you)
doesn't rediscover the same tradeoff from scratch. Distinct from
`BACKLOG.md`, which tracks completed sprints; this tracks open questions
and postponed scope.

---

## Batch / remise-level architecture — deferred (2026-09-08)

**Decision**: stay app-only for now — one traite processed per
request/analysis, as the app already works today. Not building the
`Remise` entity (TR-103) or anything that depends on it yet.

**Why this is a real, known gap, not an oversight**: the functional spec
(`20260707 IA AGENTIC TOILETTAGE TRAITE.pdf`) explicitly scopes the
périmètre applicatif around the *remise* (§1.2: "l'automatisation des
contrôles de complétude et de conformité des **remises**... la gestion du
cycle de vie des **remises**"), and states batch/volume capacity as a real
enjeu SI (§1.3: "10 000 à 20 000 remises/an... capacité de traitement en
lot, performance et scalabilité de la solution"). The Sprint 11 decision
to drop Celery/Redis was made *before* this spec was shared, under the
explicit assumption "pas de batch, que des scénarios app" — that
assumption is now known to directly contradict the spec, not just be an
unrelated simplification. Deferring it is a conscious choice, made with
that contradiction on the table, not a case of not knowing about it.

**What's blocked by this deferral** — don't schedule these until the
remise-level architecture is revisited:
- TR-103 — the `Remise` entity itself (bordereau, code contrat, contrôle
  d'unicité, regroupement multi-traites/factures)
- TR-112 — couverture facture/IP par débiteur (needs multi-traite grouping)
- TR-113 — saisie manuelle des avoirs (tied to the same per-débiteur view)
- TR-114 — extraction adhérent depuis les factures (needs facture ingestion,
  which needs a remise to attach it to)
- TR-123 — écran de synthèse OK/KO par rubrique (only meaningful at remise
  level)
- TR-124 — vérification IP par débiteur / BC par facture (needs a BC model,
  itself only meaningful inside a remise)

**What's still buildable today, unaffected by this deferral** — these
operate at the single-traite level the app already has:
- TR-102 — identification par RIB (P0, next up)
- TR-121 — double vérification N°L-CN via code-barres
- TR-122 — domiciliation + code étab/agence/compte/clé structurés
- TR-111 — cohérence montant chiffres ↔ lettres
- TR-131/132/133 — items needing business clarification before any code

**Revisit when**: real pointe-journalière volume is chiffré (see TR-101's
original acceptance criteria), or when remise-level features become
blocking for another reason.
