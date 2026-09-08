/**
 * Hand-written to mirror back/app/schemas/traite.py field-for-field. No
 * OpenAPI codegen yet (small enough surface that it isn't worth the extra
 * moving part) — if this drifts from the backend, the fix is to update
 * both sides together, the same way any hand-maintained contract works.
 */
export type TraiteStatut =
  | "À traiter"
  | "En cours OCR"
  | "Écarts à traiter"
  | "Contrôle manuel requis"
  | "Renvoyée"
  | "Fraude signalée"
  | "Validée";

export type Face = "recto" | "verso";
export type VerificationCode = "sigTire" | "accept" | "sigTireur" | "endos";
export type StatutVerification = "conforme" | "anomalie";
export type TypeDecision = "validee" | "renvoi" | "fraude";
export type RoleNlp = "tireur" | "tire" | "ordre";
export type MentionStatut = "ok" | "warn" | "absent";
export type MethodeIdentification = "rib" | "nom_seul";

export interface TraiteDocumentRead {
  id: string;
  face: Face;
  fichier_nom: string;
  content_type: string;
  taille_octets: number;
  uploaded_at: string;
}

export interface VerificationManuelleRead {
  id: string;
  code_verification: VerificationCode;
  statut: StatutVerification | null;
  verifie_par: string | null;
  verifie_le: string | null;
}

export interface DecisionRead {
  id: string;
  type: TypeDecision;
  commentaire: string | null;
  decide_par: string;
  decide_le: string;
}

export interface RecommandationRead {
  titre: string;
  detail: string;
}

export interface ChampExtraitRead {
  id: string;
  nom_champ: string;
  occurrence: number;
  valeur: string | null;
  source: "ocr" | "nlp" | "manuel";
  confiance: string | null;
}

export interface RapprochementNlpRead {
  id: string;
  role: RoleNlp;
  valeur_scan: string;
  valeur_referentiel: string | null;
  score: string;
  code_adherent_matche: string | null;
  code_debiteur_matche: string | null;
  methode_identification: MethodeIdentification;
  alerte_ecart_nom: boolean;
}

export interface MentionRead {
  code: string;
  label: string;
  valeur: string | null;
  statut: MentionStatut;
}

export interface RegleDateRead {
  label: string;
  valeur_a: string | null;
  valeur_b: string | null;
  ok: boolean | null;
}

export interface TraiteRead {
  id: string;
  numero_lcn: string;
  montant: string;
  date_echeance: string;
  date_creation_traite: string;
  date_reception: string;
  statut: TraiteStatut;
  code_adherent: string | null;
  code_debiteur: string | null;
  tireur_nom: string | null;
  tire_nom: string | null;
  created_at: string;
  updated_at: string;
}

export interface TraiteDetail extends TraiteRead {
  documents: TraiteDocumentRead[];
  champs_extraits: ChampExtraitRead[];
  rapprochements_nlp: RapprochementNlpRead[];
  verifications_manuelles: VerificationManuelleRead[];
  decisions: DecisionRead[];
  bloque: boolean;
  motif_blocage: string | null;
  recommandation: RecommandationRead;
  mentions: MentionRead[];
  regles_dates: RegleDateRead[];
  num_facture_rapprochee: string | null;
}

export interface TraitePage {
  items: TraiteRead[];
  total: number;
  page: number;
  per_page: number;
}

export interface TraiteStatusRead {
  statut: TraiteStatut;
  en_cours: boolean;
}

export interface TraiteCountsRead {
  par_statut: Record<TraiteStatut, number>;
}

export interface TraiteCreate {
  numero_lcn?: string;
  montant?: string;
  date_echeance?: string;
  date_creation_traite?: string;
}

export interface ApiErrorBody {
  detail: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
}
