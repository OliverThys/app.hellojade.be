"""
Service LLM Mistral pour HelloJADE – analyse des réponses patients.

Rôle : parser la réponse vocale transcrite d'un patient (texte brut issu de
l'Azure STT) en une réponse normalisée selon le type de question.

Priorité : API Mistral (mistral-small-latest) via httpx.
Fallback : Azure OpenAI GPT-4o-mini si MISTRAL_API_KEY absent ou erreur.

Retour structuré (JSON) :
{
    "answer":        "oui" | "non" | "5" | "légèrement" | "texte court" | "",
    "confidence":    0.0 – 1.0,
    "understood":    true | false,
    "out_of_scope":  true | false,
    "notes":         "observation médicale ou null"
}

NOTE : la logique d'alerte est intentionnellement codée en dur dans
azure_call_service.py (déterministe, fiable, auditables). Mistral se limite
au parsing de la parole naturelle → réponse normalisée.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT SYSTÈME
# ─────────────────────────────────────────────────────────────────────────────

_IDENTITY_SYSTEM_PROMPT = """Tu es un assistant de vérification d'identité pour un hôpital belge.

Le patient vient de répondre par téléphone à la question :
"Pouvez-vous me confirmer votre nom, prénom et date de naissance ?"

La transcription provient d'un système STT automatique et peut contenir des erreurs phonétiques, \
notamment sur les noms propres.

Évalue si la transcription correspond à l'identité attendue selon ces règles STRICTES :

RÈGLES :
• match=true UNIQUEMENT si les deux conditions suivantes sont remplies :
  1. La date de naissance est présente et correspond à la date attendue \
(formats acceptés : "16 janvier 2002", "16/01/2002", "16/01/02", "seize du premier deux mille deux", \
"seize janvier deux mille deux", "le 16 du 1 2002", "le seize du un deux mille deux", etc. \
— les années à 2 chiffres comme "02" ou "97" sont acceptées \
— format belge "le J du M AAAA" est accepté (ex. "le 25 du 7 1997" = 25 juillet 1997) \
— IMPORTANT : le STT peut fusionner le mois et l'année en un seul nombre (ex. "120002" = mois 1 + année 2002, \
"71997" = mois 7 + année 1997) — dans ce cas, tente de décomposer le nombre et vérifie si le résultat correspond)
  2. Au moins un des deux éléments est reconnaissable : le NOM ou le PRÉNOM \
(variations orthographiques et erreurs STT tolérées)
• match=false si : date absente, date incorrecte, ou ni le nom ni le prénom ne sont reconnaissables.
• Nom + prénom sans date → match=false (la date est OBLIGATOIRE).
• Si ddn est vide ("") : la condition sur la date est ignorée, seul nom ou prénom suffit.
• Tolérance élevée aux erreurs STT sur les noms propres (ex. "Dupond" pour "Dupont" → acceptable).

Retourne UNIQUEMENT un objet JSON : {"match": true, "confidence": 0.95}
Clés obligatoires : match (booléen), confidence (0.0–1.0). Aucun texte autour."""

_SYSTEM_PROMPT_PROCHE_NOTE = (
    "\nL'interlocuteur est un **proche** du patient (famille, aidant) — "
    "il parle à la troisième personne "
    "(\"il a mal\", \"elle mange bien\", \"il prend du Dafalgan\"). "
    "Normalise sa réponse exactement comme si c'était la réponse du patient lui-même "
    "(ex. \"il a mal\" → yesno=\"oui\", \"elle mange normalement\" → yesno=\"oui\").\n"
)

def _build_system_prompt(caller_role: str = "patient") -> str:
    proche_note = _SYSTEM_PROMPT_PROCHE_NOTE if caller_role == "proche" else ""
    speaker = "d'un proche de patient" if caller_role == "proche" else "de patients"
    intro = (
        f"Tu es un assistant médical qui analyse les réponses verbales {speaker} "
        "lors d'appels de suivi post-hospitalisation.\n\n"
        "La réponse provient d'une transcription automatique (STT), "
        "elle peut contenir des erreurs phonétiques ou des formulations familières."
        f"{proche_note}"
    )
    return intro + _SYSTEM_PROMPT_RULES


_SYSTEM_PROMPT_RULES = """

RÈGLES DE NORMALISATION (uniquement si out_of_scope est false) :
• yesno  → réponds "oui" ou "non" uniquement
  - Affirmations: "oui", "ouais", "bien sûr", "effectivement", "tout à fait", "c'est ça", \
"j'ai mal" → "oui"
  - Négations: "non", "pas du tout", "ça va", "pas vraiment", "je ne crois pas" → "non"
• score   → extrait un entier 0-10 (les mots: "cinq"→5, "sept"→7, etc.)
• choice  → renvoie l'une des valeurs listées dans choices (la plus proche sémantiquement)
• open    → résumé court (max 10 mots) de ce que dit le patient

Si la réponse est vide, inaudible ou incompréhensible, mets understood=false et out_of_scope=false.

MÉTA-RÉPONSE (demande de clarification, pas hors sujet) : si le patient dit qu'il n'a pas compris, \
veut que tu répètes, ou demande le sens de la question (ex. "pardon ?", "répétez", \
"je n'ai pas compris"), mets understood=false, out_of_scope=false, confidence=0.1. \
Ne pas interpréter la négation grammaticale comme un "non" médical.

Formules de politesse en fin de phrase : si le patient répond au fond PUIS ajoute une politesse \
(ex. « non pas de douleur, bien compris »), extrais uniquement la réponse médicale (« non ») \
avec understood=true. \
IMPORTANT : si la transcription ne contient QUE une formule de politesse sans contenu médical — \
exemples : « bien compris », « OK merci », « c'est bon », « merci », « d'accord merci », \
« bonjour », « bonsoir » — alors tu DOIS mettre understood=false ET answer="" (chaîne vide). \
Ne jamais mettre understood=true avec answer="" pour une question yesno, score ou choice.

ANTICIPATION : si le patient, en répondant à la question actuelle, donne aussi l'information \
pour une ou plusieurs questions futures, extrais ces réponses dans le champ "pre_answered". \
Ce champ est un objet {"id_question": "réponse_normalisée"}, ex. {"Q3b_vomissements_repetes": "non"}. \
N'inclure dans "pre_answered" QUE les questions dont l'ID figure dans la liste \
"Questions suivantes (IDs)" fournie dans le message utilisateur. \
Pour la question ACTUELLE, utilise uniquement l'information qui y répond directement. \
Si aucune anticipation n'est détectée, omets "pre_answered" ou mets {}.

SYMPTÔME DÉCRIT COMME RÉPONSE IMPLICITE (PRIORITAIRE) : pour une question yesno portant sur des \
symptômes, douleurs, ou état de santé, si le patient décrit un symptôme physique ou une plainte \
médicale au lieu de dire "oui/non", cela constitue une réponse implicite "oui". \
Tu DOIS mettre answer="oui", out_of_scope=false, understood=true, \
et noter le symptôme décrit en résumé court dans le champ "notes". \
Exemples : \
"j'ai du sang dans les selles" → answer="oui", notes="sang dans les selles" ; \
"j'ai du mal à respirer" → answer="oui", notes="gêne respiratoire" ; \
"j'ai de la fièvre depuis hier" → answer="oui", notes="fièvre depuis hier" ; \
"j'ai une douleur dans la poitrine" → answer="oui", notes="douleur thoracique" ; \
"mon ventre est gonflé" → answer="oui", notes="ventre gonflé / ballonnement". \
Cette règle s'applique à TOUTES les questions yesno médicales, quelle que soit la liste de \
symptômes mentionnée dans la question.

HORS PÉRIMÈTRE (clé out_of_scope) : tu DOIS toujours inclure "out_of_scope": true ou false.

Mets "out_of_scope": true si le patient NE RÉPOND PAS à la question posée, par exemple :
• il parle d'autre chose (envies alimentaires, parking, administratif, météo) sans répondre au sujet ;
• il pose une question au lieu de répondre (sauf méta « je n'ai pas compris » → voir ci‑dessous) ;
• la transcription évoque un sujet sans lien avec la question médicale \
(ex. sur une question symptôme oui/non, il ne dit que « j'ai envie de manger des pâtes » \
sans mentionner aucun symptôme physique).

Dans ce cas : understood=true, out_of_scope=true, answer "" (chaîne vide pour yesno/score/choice), \
confidence entre 0.75 et 1.0, notes null ou courte observation.

Mets "out_of_scope": false si le patient répond réellement au type de question \
(oui/non explicite ou implicite via description de symptôme, score, choix, résumé open).

Rétrocompat : si out_of_scope est absent mais notes vaut exactement out_of_scope, traite comme hors périmètre.

Retourne UNIQUEMENT un objet JSON valide, sans markdown, sans explication. \
Clés obligatoires : answer, confidence, understood, out_of_scope (booléen), notes. \
Clé optionnelle : pre_answered (objet vide {} si absent). \
Exemple minimal : {"answer": "", "confidence": 0.9, "understood": true, "out_of_scope": false, "notes": null, "pre_answered": {}}"""

# Prompt par défaut (patient) — garde la compatibilité avec le reste du code
_SYSTEM_PROMPT = _build_system_prompt("patient")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extrait le premier objet JSON valide d'une chaîne (tolère le texte autour)."""
    # Chercher {...} dans la réponse
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _fallback_parse(
    patient_response: str,
    question_type: str,
    choices: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Parser de secours purement régulier (si Mistral est indisponible).
    Couvre les cas les plus simples pour ne pas bloquer le questionnaire.
    """
    text = patient_response.lower().strip()

    oob_false: Dict[str, Any] = {"out_of_scope": False}

    if not text:
        return {"answer": "", "confidence": 0.0, "understood": False, "out_of_scope": False, "notes": None}

    if question_type == "yesno":
        # Retirer les queues purement polies pour détecter oui/non sur le fond
        tstrip = text
        for tail in (
            "bien compris",
            "c'est bon",
            "ok merci",
            "merci bien",
            "d'accord merci",
            "merci beaucoup",
        ):
            if tstrip.endswith(tail):
                tstrip = tstrip[: -len(tail)].strip().rstrip(",.;:!?")
        if not tstrip:
            return {
                **oob_false,
                "answer": "",
                "confidence": 0.15,
                "understood": False,
                "notes": "Formule sans contenu médical",
            }
        text = tstrip

        yes_words = ("oui", "ouais", "bien sûr", "effectivement", "tout à fait",
                     "j'ai mal", "oui madame", "oui monsieur", "yes")
        no_words = ("non", "pas du tout", "ça va", "pas vraiment", "je ne crois pas",
                    "aucun", "aucune", "no")
        # Marqueurs de symptômes — réponse implicite "oui" (description physique)
        symptom_markers = (
            "j'ai du", "j'ai de la", "j'ai des", "j'ai un", "j'ai une",
            "je saigne", "je vomis", "j'urine", "je tousse", "je souffre",
            "je ressens", "j'ai du mal", "j'ai de la difficulté", "j'ai de la peine",
            "du sang", "de la fièvre", "de la douleur", "des douleurs",
            "essoufflement", "gonflement", "enflure", "rougeur", "écoulement",
        )
        if any(w in text for w in yes_words):
            return {**oob_false, "answer": "oui", "confidence": 0.8, "understood": True, "notes": None}
        if any(w in text for w in no_words):
            return {**oob_false, "answer": "non", "confidence": 0.8, "understood": True, "notes": None}
        if any(w in text for w in symptom_markers):
            symptom_note = text[:60] if len(text) > 60 else text
            return {
                **oob_false,
                "answer": "oui",
                "confidence": 0.7,
                "understood": True,
                "notes": symptom_note,
            }
        return {
            **oob_false,
            "answer": "non",
            "confidence": 0.4,
            "understood": True,
            "notes": "Réponse ambiguë – interprété comme non",
        }

    if question_type == "score":
        # Chercher un chiffre
        nums = re.findall(r"\b([0-9]|10)\b", text)
        word_map = {"zéro": 0, "un": 1, "deux": 2, "trois": 3, "quatre": 4,
                    "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10}
        if nums:
            return {**oob_false, "answer": str(nums[0]), "confidence": 0.9, "understood": True, "notes": None}
        for word, num in word_map.items():
            if word in text:
                return {**oob_false, "answer": str(num), "confidence": 0.85, "understood": True, "notes": None}
        return {
            **oob_false,
            "answer": "5",
            "confidence": 0.3,
            "understood": False,
            "notes": "Score non détecté – valeur par défaut",
        }

    if question_type == "choice" and choices:
        for choice in choices:
            if choice.lower() in text:
                return {**oob_false, "answer": choice, "confidence": 0.85, "understood": True, "notes": None}
        return {
            **oob_false,
            "answer": choices[0],
            "confidence": 0.3,
            "understood": False,
            "notes": "Choix non reconnu – premier choix par défaut",
        }

    # open
    summary = text[:80] if len(text) > 80 else text
    return {**oob_false, "answer": summary, "confidence": 0.7, "understood": True, "notes": None}


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE
# ─────────────────────────────────────────────────────────────────────────────

def parsed_is_out_of_scope(parsed: Dict[str, Any]) -> bool:
    """True si le LLM a classé la réponse comme hors questionnaire."""
    o = parsed.get("out_of_scope")
    if o is True:
        return True
    if isinstance(o, str) and o.strip().lower() in ("true", "1", "yes", "oui"):
        return True
    notes = parsed.get("notes")
    if notes is None:
        return False
    normalized = str(notes).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized == "out_of_scope"


class MistralService:
    """
    Analyse les réponses patients via l'API Mistral (mistral-small-latest).

    Fallback automatique sur Azure OpenAI GPT-4o-mini si Mistral est
    indisponible, puis sur le parser régulier si les deux échouent.
    """

    @staticmethod
    def normalize_parsed_response(parsed: Dict[str, Any]) -> Dict[str, Any]:
        """Uniformise out_of_scope et notes (variantes LLM)."""
        out = dict(parsed)
        n = out.get("notes")
        if isinstance(n, str) and "out" in n.lower() and "scope" in n.lower():
            out["notes"] = "out_of_scope"
        o = out.get("out_of_scope")
        if isinstance(o, str):
            out["out_of_scope"] = o.strip().lower() in ("true", "1", "yes", "oui")
        if parsed_is_out_of_scope(out) and out.get("out_of_scope") is not True:
            out["out_of_scope"] = True
        if out.get("out_of_scope") is True:
            out["understood"] = True
            # Évite un oui/non résiduel si le modèle remplit les deux champs incorrectement
            out["answer"] = ""
        return out

    @staticmethod
    def parsed_is_out_of_scope(parsed: Dict[str, Any]) -> bool:
        return parsed_is_out_of_scope(parsed)

    def __init__(self):
        self.mistral_api_key = settings.MISTRAL_API_KEY
        self.mistral_model = settings.MISTRAL_MODEL
        self.mistral_base_url = settings.MISTRAL_BASE_URL.rstrip("/")

        self.azure_endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        self.azure_api_key = settings.AZURE_OPENAI_API_KEY
        self.azure_deployment = settings.AZURE_OPENAI_DEPLOYMENT

        # Client persistant : évite la reconnexion TLS (~150-300ms) à chaque appel.
        # Le client vit pour toute la durée du processus (pas de close explicite nécessaire).
        self._http_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    @property
    def mistral_available(self) -> bool:
        return bool(self.mistral_api_key)

    @property
    def azure_openai_available(self) -> bool:
        return bool(self.azure_endpoint and self.azure_api_key)

    @staticmethod
    def _normalize(s: str) -> str:
        """Minuscules sans accents, pour comparaison tolérante aux erreurs STT."""
        s = s.lower().strip()
        s = unicodedata.normalize("NFD", s)
        return "".join(c for c in s if unicodedata.category(c) != "Mn")

    @staticmethod
    def _fix_stt_date_merging(transcript: str) -> str:
        """
        Corrige la fusion STT du mois et de l'année en un seul nombre.

        Exemple : "le 16 du 120002" → "le 16 du 1 2002"
                  "le 25 du 71997"  → "le 25 du 7 1997"

        Le STT fusionne parfois "un deux mille deux" en "120002" quand le
        locuteur enchaîne le mois (1) et l'année (2002) sans pause.
        Pattern : nombre N où les 4 derniers chiffres forment une année
        plausible (1900-2099) et le préfixe est un mois valide (1-12).
        """
        def split_month_year(m: re.Match) -> str:
            n = m.group(0)
            if len(n) < 5:
                return n
            year_candidate = n[-4:]
            month_candidate = n[:-4]
            year_int = int(year_candidate)
            month_int = int(month_candidate) if month_candidate.isdigit() else 0
            if 1900 <= year_int <= 2099 and 1 <= month_int <= 12:
                return f"{month_candidate} {year_candidate}"
            return n

        return re.sub(r"\b\d{5,6}\b", split_month_year, transcript)

    @staticmethod
    def _word_in(word: str, text: str) -> bool:
        """Vérifie qu'un mot apparaît comme token isolé (bornes \b) dans text."""
        return bool(re.search(r"\b" + re.escape(word) + r"\b", text))

    def _identity_fallback(self, transcript: str, nom: str, prenom: str, ddn_str: str) -> bool:
        """
        Vérification purement Python (si Mistral et Azure OpenAI sont indisponibles).
        Règles : date OBLIGATOIRE (si ddn_str renseignée) + nom OU prénom.
        La date est vérifiée sur le jour, le mois ET l'année (4 ou 2 chiffres).
        Correspondances par token entier (\b) pour éviter les faux positifs.
        """
        t = self._normalize(transcript)

        if ddn_str:
            parts = ddn_str.split()  # ["25", "juillet", "1997"]
            if len(parts) < 3:
                return False
            day, month_fr, year_full = parts[0], parts[1], parts[2]
            year_short = year_full[-2:]  # "97"

            year_ok = self._word_in(year_full, transcript) or self._word_in(year_short, t)
            day_ok = self._word_in(day, transcript)
            month_ok = self._word_in(self._normalize(month_fr), t)
            if not (year_ok and day_ok and month_ok):
                return False

        nom_ok = self._normalize(nom) in t if nom else False
        prenom_ok = self._normalize(prenom) in t if prenom else False
        return nom_ok or prenom_ok

    async def verify_identity(
        self,
        transcript: str,
        nom: str,
        prenom: str,
        ddn_str: str,
    ) -> bool:
        """
        Vérifie que la transcription STT correspond à l'identité attendue du patient.

        Règles (par ordre de priorité) :
        1. Précheck Python : si (prénom OU nom) + date de naissance → True immédiatement.
           Cela couvre les cas où le STT déforme légèrement le nom (ex. "Thys" → "this")
           mais le prénom et la date sont corrects.
        2. Si le précheck échoue, Mistral analyse pour les formulations complexes.
        3. Fallback Python si Mistral est indisponible.
        """
        if not transcript.strip():
            return False

        # ── 0. Normalisation STT : corriger les fusions mois+année ───────────
        transcript = self._fix_stt_date_merging(transcript)

        # ── 1. Précheck Python rapide (pas d'appel LLM) ──────────────────────
        if self._identity_fallback(transcript, nom, prenom, ddn_str):
            logger.info("[IDENTITY] Précheck Python → match=True (prénom/nom + date OK)")
            return True

        # ── 2. Mistral pour les cas complexes ────────────────────────────────
        user_content = (
            f"Identité attendue :\n"
            f"- Nom : {nom or '(non renseigné)'}\n"
            f"- Prénom : {prenom or '(non renseigné)'}\n"
            f"- Date de naissance : {ddn_str or '(non renseignée)'}\n\n"
            f"Transcription du patient (après correction STT) : \"{transcript}\"\n\n"
            "Retourne un JSON {\"match\": bool, \"confidence\": float}."
        )

        for provider, available, call_fn in [
            ("Mistral", self.mistral_available, self._verify_via_mistral),
            ("AzureOAI", self.azure_openai_available, self._verify_via_azure_openai),
        ]:
            if available:
                result = await call_fn(user_content)
                if result is not None:
                    match = bool(result.get("match", False))
                    logger.info(
                        f"[{provider}] verify_identity → match={match} "
                        f"conf={result.get('confidence', '?')}"
                    )
                    return match

        logger.warning("[IDENTITY] LLM indisponible — fallback Python substring")
        return False

    async def _verify_via_mistral(self, user_content: str) -> Optional[Dict[str, Any]]:
        try:
            resp = await self._http_client.post(
                f"{self.mistral_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.mistral_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.mistral_model,
                    "messages": [
                        {"role": "system", "content": _IDENTITY_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 60,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            return _extract_json(raw)
        except Exception as exc:
            logger.error(f"[MISTRAL] verify_identity error: {exc}")
            return None

    async def _verify_via_azure_openai(self, user_content: str) -> Optional[Dict[str, Any]]:
        url = (
            f"{self.azure_endpoint}/openai/deployments/"
            f"{self.azure_deployment}/chat/completions?api-version=2024-02-01"
        )
        try:
            resp = await self._http_client.post(
                url,
                headers={
                    "api-key": self.azure_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "messages": [
                        {"role": "system", "content": _IDENTITY_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 60,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            return _extract_json(raw)
        except Exception as exc:
            logger.error(f"[AZURE_OAI] verify_identity error: {exc}")
            return None

    async def analyze_response(
        self,
        question_id: str,
        question_text: str,
        question_type: str,
        patient_response: str,
        choices: Optional[list] = None,
        upcoming_context: Optional[str] = None,
        upcoming_questions: Optional[list] = None,
        caller_role: str = "patient",
    ) -> Dict[str, Any]:
        """
        Parse la réponse vocale du patient selon le type de question.

        Args:
            question_id:         Identifiant de la question (ex. "Q1_douleur")
            question_text:       Texte de la question posée
            question_type:       Type : yesno | score | choice | open
            patient_response:    Transcription brute de la réponse du patient
            choices:             Liste des choix valides (si question_type=choice)
            upcoming_questions:  Liste de dicts {id, text, type} des questions suivantes
                                 (pour que Mistral puisse extraire pre_answered)

        Returns:
            dict avec les clés : answer, confidence, understood, out_of_scope, notes,
            et optionnellement pre_answered : {question_id: answer_normalisée}
        """
        if not patient_response.strip():
            logger.info(f"[MISTRAL] Réponse vide pour {question_id}")
            return {
                "answer": "",
                "confidence": 0.0,
                "understood": False,
                "out_of_scope": False,
                "notes": "Aucune réponse",
            }

        # Tenter Mistral d'abord
        if self.mistral_available:
            result = await self._call_mistral(
                question_id,
                question_text,
                question_type,
                patient_response,
                choices,
                upcoming_context,
                upcoming_questions,
                caller_role=caller_role,
            )
            if result:
                return result

        # Fallback Azure OpenAI
        if self.azure_openai_available:
            result = await self._call_azure_openai(
                question_id,
                question_text,
                question_type,
                patient_response,
                choices,
                upcoming_context,
                upcoming_questions,
            )
            if result:
                return result

        # Fallback parseur régulier
        logger.warning(
            f"[MISTRAL] LLM indisponible pour {question_id} – parseur de secours"
        )
        return _fallback_parse(patient_response, question_type, choices)

    async def _call_mistral(
        self,
        question_id: str,
        question_text: str,
        question_type: str,
        patient_response: str,
        choices: Optional[list],
        upcoming_context: Optional[str] = None,
        upcoming_questions: Optional[list] = None,
        caller_role: str = "patient",
    ) -> Optional[Dict[str, Any]]:
        """Appel à l'API Mistral via httpx."""
        user_content = self._build_user_message(
            question_text, question_type, patient_response, choices, upcoming_context,
            upcoming_questions,
        )

        try:
            resp = await self._http_client.post(
                f"{self.mistral_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.mistral_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.mistral_model,
                    "messages": [
                        {"role": "system", "content": _build_system_prompt(caller_role)},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 100,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()

            raw = resp.json()["choices"][0]["message"]["content"]
            parsed = _extract_json(raw)
            if parsed:
                logger.info(
                    f"[MISTRAL] {question_id} → answer='{parsed.get('answer')}' "
                    f"oob={parsed.get('out_of_scope')} conf={parsed.get('confidence', '?')} "
                    f"pre_answered={parsed.get('pre_answered') or {}}"
                )
                return parsed

            logger.warning(f"[MISTRAL] JSON invalide dans la réponse: {raw[:200]}")
        except httpx.HTTPStatusError as exc:
            logger.error(f"[MISTRAL] HTTP {exc.response.status_code}: {exc.response.text[:200]}")
        except Exception as exc:
            logger.error(f"[MISTRAL] Exception: {exc}", exc_info=True)

        return None

    async def _call_azure_openai(
        self,
        question_id: str,
        question_text: str,
        question_type: str,
        patient_response: str,
        choices: Optional[list],
        upcoming_context: Optional[str] = None,
        upcoming_questions: Optional[list] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fallback Azure OpenAI GPT-4o-mini."""
        user_content = self._build_user_message(
            question_text, question_type, patient_response, choices, upcoming_context,
            upcoming_questions,
        )
        url = (
            f"{self.azure_endpoint}/openai/deployments/"
            f"{self.azure_deployment}/chat/completions?api-version=2024-02-01"
        )

        try:
            resp = await self._http_client.post(
                url,
                headers={
                    "api-key": self.azure_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 100,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()

            raw = resp.json()["choices"][0]["message"]["content"]
            parsed = _extract_json(raw)
            if parsed:
                logger.info(
                    f"[AZURE_OAI] {question_id} → answer='{parsed.get('answer')}' "
                    f"oob={parsed.get('out_of_scope')} conf={parsed.get('confidence', '?')}"
                )
                return parsed
        except Exception as exc:
            logger.error(f"[AZURE_OAI] Exception: {exc}", exc_info=True)

        return None

    @staticmethod
    def _build_user_message(
        question_text: str,
        question_type: str,
        patient_response: str,
        choices: Optional[list],
        upcoming_context: Optional[str] = None,
        upcoming_questions: Optional[list] = None,
    ) -> str:
        lines = [
            f"Question posée au patient : {question_text}",
            f"Type de question : {question_type}",
        ]
        if choices:
            lines.append(f"Choix valides : {', '.join(choices)}")
        if upcoming_context:
            lines.append(upcoming_context)
        if upcoming_questions:
            id_lines = [
                f'  - {q["id"]} ({q.get("type", "yesno")}) : "{q.get("text", "")}"'
                for q in upcoming_questions
            ]
            lines.append(
                "Questions suivantes (IDs à utiliser dans pre_answered si le patient y répond déjà) :\n"
                + "\n".join(id_lines)
            )
        lines.append(f'Réponse du patient (transcription STT) : "{patient_response}"')
        lines.append(
            "Réponse attendue : un seul objet JSON avec les clés "
            "answer, confidence, understood, out_of_scope (booléen obligatoire), notes, "
            "et pre_answered ({} si aucune anticipation)."
        )
        return "\n".join(lines)


# Instance globale
mistral_service = MistralService()
