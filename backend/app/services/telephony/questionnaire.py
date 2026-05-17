"""
Questionnaire médical post-hospitalisation hellojade — Maolys.

Modèle par défaut et repli si la base ne contient pas de questions actives.
Les appels en production chargent de préférence le questionnaire depuis la DB
(voir questionnaire_loader). Indépendant du fournisseur téléphonique.
"""
from typing import Any, Dict, List, Optional

# Durées d'enregistrement (secondes)
RECORD_DURATION_SHORT = 10
RECORD_DURATION_LONG = 20

WELCOME_MESSAGE = (
    "Bonjour, je suis Jade, l'assistante vocale hellojade. "
    "Je vous appelle dans le cadre d'une démonstration de suivi post-hospitalisation."
)

# ── Phase destinataire ────────────────────────────────────────────────────────
# {{prénom}} et {{nom}} sont substitués par _get_message() dans le service ARI.

PERSON_CHECK_QUESTION = (
    "Suis-je bien en ligne avec {{prénom}} {{nom}} ?"
)

PERSON_CHECK_RETRY = (
    "Excusez-moi, je n'ai pas bien compris. "
    "Êtes-vous bien {{prénom}} {{nom}} ?"
)

PROCHE_QUESTION = (
    "Je comprends. Êtes-vous un proche de {{prénom}} {{nom}} ?"
)

PERSON_NOT_FOUND_MESSAGE = (
    "Je suis désolée pour le dérangement. "
    "Je rappellerai ultérieurement. Au revoir."
)

CONSENT_QUESTION = (
    "Cet appel sera enregistré. "
    "Avez-vous quelques minutes pour répondre à quelques questions "
    "sur votre état de santé depuis votre sortie ?"
)

CONSENT_QUESTION_PROCHE = (
    "Cet appel sera enregistré. "
    "Avez-vous quelques minutes pour répondre à quelques questions "
    "sur l'état de santé de {{prénom}} {{nom}} depuis sa sortie ?"
)

CONSENT_REFUSED_MESSAGE = (
    "Je comprends tout à fait. "
    "N'hésitez pas à nous recontacter si vous avez le moindre doute. Au revoir."
)

# ── Clôture — variantes aidant proche ────────────────────────────────────────

CLOSING_MESSAGE_NORMAL_PROCHE = (
    "Je vous remercie pour vos réponses — elles ont bien été enregistrées dans le système. "
    "Si le patient ressent un symptôme nouveau ou inquiétant dans les prochains jours, "
    "n'hésitez pas à consulter un professionnel de santé. "
    "Prenez soin de lui, et au revoir."
)

CLOSING_MESSAGE_TRANSFER_FAILED_PROCHE = (
    "Je n'ai pas pu joindre l'équipe médicale immédiatement. "
    "Notre équipe va rappeler très prochainement. "
    "En cas d'urgence, composez le 112. "
    "Au revoir."
)

QUESTIONNAIRE: List[Dict[str, Any]] = [
    {
        "id": "Q1_douleur",
        "question": "Avez-vous mal quelque part depuis votre sortie ?",
        "question_proche": "Le patient a-t-il mal quelque part depuis sa sortie ?",
        "type": "yesno",
        "record_duration": RECORD_DURATION_SHORT,
        "follow_ups": [
            {
                "id": "Q1a_score_douleur",
                "condition": "oui",
                "question": (
                    "Sur une échelle de zéro à dix — zéro étant aucune douleur "
                    "et dix une douleur insupportable — quel chiffre donneriez-vous à cette douleur ?"
                ),
                "question_proche": (
                    "Sur une échelle de zéro à dix — zéro étant aucune douleur "
                    "et dix une douleur insupportable — quel chiffre donneriez-vous à sa douleur ?"
                ),
                "type": "score",
                "record_duration": RECORD_DURATION_SHORT,
                "alert_if_gte": 7,
            },
            {
                "id": "Q1b_empeche_dormir",
                "condition": "oui",
                "question": "Cette douleur vous empêche-t-elle de dormir ou de vous déplacer normalement ?",
                "question_proche": "Cette douleur l'empêche-t-elle de dormir ou de se déplacer normalement ?",
                "type": "yesno",
                "record_duration": RECORD_DURATION_SHORT,
            },
            {
                "id": "Q1c_intolerable",
                "condition": "oui",
                "question": (
                    "Concernant la douleur dont vous parliez : "
                    "la trouvez-vous intolérable, ou a-t-elle tendance à s'aggraver ?"
                ),
                "question_proche": (
                    "Concernant la douleur dont vous parliez : "
                    "la trouve-t-il intolérable, ou a-t-elle tendance à s'aggraver ?"
                ),
                "type": "yesno",
                "record_duration": RECORD_DURATION_SHORT,
                "alert_if": "oui",
            },
            {
                "id": "Q1d_antidouleurs",
                "condition": "oui",
                "question": (
                    "En ce moment, prenez-vous des antidouleurs ? "
                    "Et si oui, vous soulagent-ils totalement, moyennement, légèrement, ou pas du tout ?"
                ),
                "question_proche": (
                    "En ce moment, prend-il des antidouleurs ? "
                    "Et si oui, le soulagent-ils totalement, moyennement, légèrement, ou pas du tout ?"
                ),
                "type": "choice",
                "choices": ["totalement", "moyennement", "légèrement", "pas du tout", "non"],
                "record_duration": RECORD_DURATION_SHORT,
            },
            {
                "id": "Q1e_type_antidouleur",
                # Posée uniquement si le patient prend des antidouleurs (Q1d ≠ "non")
                # condition_parent_id pointe vers la sous-question parente (pas la question principale)
                "condition_parent_id": "Q1d_antidouleurs",
                "condition": ["totalement", "moyennement", "légèrement", "pas du tout"],
                "question": "Quel médicament prenez-vous, et à quelle dose ?",
                "question_proche": "Quel médicament prend-il, et à quelle dose ?",
                "type": "open",
                "record_duration": RECORD_DURATION_LONG,
                "optional": True,
            },
        ],
    },
    {
        "id": "Q2_alimentation",
        "question": "Depuis votre sortie, vous alimentez-vous normalement ?",
        "question_proche": "Depuis sa sortie, le patient s'alimente-t-il normalement ?",
        "type": "yesno",
        "record_duration": RECORD_DURATION_SHORT,
        "follow_ups": [],
    },
    {
        "id": "Q3_nausees",
        "question": "Avez-vous des nausées ou des vomissements en ce moment ?",
        "question_proche": "Le patient a-t-il des nausées ou des vomissements en ce moment ?",
        "type": "yesno",
        "record_duration": RECORD_DURATION_SHORT,
        "follow_ups": [
            {
                "id": "Q3a_nausees_persistantes",
                "condition": "oui",
                "question": "Ces symptômes sont-ils présents en permanence tout au long de la journée ?",
                "type": "yesno",
                "record_duration": RECORD_DURATION_SHORT,
                "alert_if": "oui",
            },
            {
                "id": "Q3b_vomissements_repetes",
                "condition": "oui",
                "question": "Et les vomissements — surviennent-ils de façon répétée ?",
                "type": "yesno",
                "record_duration": RECORD_DURATION_SHORT,
                "alert_if": "oui",
            },
        ],
    },
    {
        "id": "Q4_pansement",
        "question": "Votre pansement est-il propre et sec ?",
        "question_proche": "Son pansement est-il propre et sec ?",
        "type": "yesno",
        "record_duration": RECORD_DURATION_SHORT,
        "clarification_reprompt": (
            "Je vous demande si le pansement — la compresse ou le bandage sur votre cicatrice "
            "— est propre, sans tache de sang ni écoulement, et bien sec. "
            "Est-ce le cas ?"
        ),
        "follow_ups": [
            {
                "id": "Q4a_sang",
                "condition": "non",
                "question": "Y a-t-il du sang qui traverse le pansement ?",
                "type": "yesno",
                "record_duration": RECORD_DURATION_SHORT,
                "alert_if": "oui",
            },
            {
                "id": "Q4b_ecoulement",
                "condition": "non",
                "question": "Observez-vous un écoulement autour ou au-delà du pansement ?",
                "question_proche": "Observez-vous un écoulement autour ou au-delà de son pansement ?",
                "type": "yesno",
                "record_duration": RECORD_DURATION_SHORT,
                "alert_if": "oui",
            },
        ],
    },
    {
        "id": "Q5_medecin",
        "question": "Avez-vous consulté un médecin depuis votre sortie ?",
        "question_proche": "Le patient a-t-il consulté un médecin depuis sa sortie ?",
        "type": "yesno",
        "record_duration": RECORD_DURATION_SHORT,
        "follow_ups": [
            {
                "id": "Q5a_lie_intervention",
                "condition": "oui",
                "question": "Cette consultation concernait-elle votre opération ?",
                "question_proche": "Cette consultation concernait-elle son opération ?",
                "type": "yesno",
                "record_duration": RECORD_DURATION_SHORT,
                "alert_if": "oui",
                "clarification_reprompt": (
                    "Je vous demande si le motif de cette consultation médicale "
                    "était directement lié à votre opération récente. "
                    "Était-ce le cas ?"
                ),
            },
        ],
    },
    {
        "id": "Q6_autres_symptomes",
        "question": (
            "Avez-vous d'autres symptômes préoccupants : "
            "douleur thoracique, gêne respiratoire ou problème urinaire ?"
        ),
        "question_proche": (
            "Le patient a-t-il d'autres symptômes préoccupants : "
            "douleur thoracique, gêne respiratoire ou problème urinaire ?"
        ),
        "type": "yesno",
        "record_duration": RECORD_DURATION_SHORT,
        "follow_ups": [
            {
                "id": "Q6a_symptome_detail",
                "condition": "oui",
                "question": "Pouvez-vous me décrire brièvement ce symptôme ?",
                "type": "open",
                "record_duration": RECORD_DURATION_LONG,
                "oob_reprompt": "Décrivez votre symptôme en quelques mots. Par exemple : de la fièvre, des nausées, une douleur.",
            },
        ],
        "alert_if": "oui",
    },
    {
        "id": "Q7_parler_equipe",
        "question": "Souhaitez-vous parler à quelqu'un de l'équipe médicale ?",
        "type": "yesno",
        "record_duration": RECORD_DURATION_SHORT,
        "follow_ups": [],
        "alert_if": "oui",
    },
]

CLOSING_MESSAGE_NORMAL = (
    "Je vous remercie pour vos réponses — elles ont bien été enregistrées dans le système. "
    "Si vous ressentez un symptôme nouveau ou inquiétant dans les prochains jours, "
    "n'hésitez pas à consulter un professionnel de santé. "
    "Prenez soin de vous, et bon rétablissement. Au revoir."
)

CLOSING_MESSAGE_ALERT = (
    "Certaines de vos réponses nécessitent l'avis d'un soignant. "
    "Je vous transfère — restez en ligne "
    "et soyez prêt à lui décrire vos symptômes."
)

CLOSING_MESSAGE_TRANSFER_FAILED = (
    "Je n'ai pas pu joindre l'équipe médicale immédiatement. "
    "Notre équipe va vous rappeler très prochainement. "
    "En cas d'urgence, composez le 112. "
    "Au revoir."
)

# ── Accusés de réception ──────────────────────────────────────────────────────
#
# Chaque entrée : (texte, rate SSML, pitch SSML).
# La logique de sélection est dans asterisk_ari_service.py :
#   - 60 % du temps → ACK_HUM_ENTRIES  (vocalisations d'écoute neutres)
#   - 40 % du temps → ACK_ENTRIES_NEUTRAL (brèves confirmations neutres, anti-repeat)

# Vocalisations d'écoute — ton neutre, lent, descendant
# Utiliser uniquement "Hum hum." (mot français) : "Hm" et "Mmh" sont épelés comme lettres par Azure TTS.
ACK_HUM_ENTRIES: list[tuple[str, str, str]] = [
    # texte          rate    pitch
    ("Hum hum.",     "-10%", "-5%"),
    ("Hum hum.",     "-15%", "-8%"),
    ("Hum hum.",     "-8%",  "-3%"),
]

# Confirmations neutres — aucun enthousiasme, aucun jugement de valeur
ACK_ENTRIES_NEUTRAL: list[tuple[str, str, str]] = [
    # texte              rate      pitch
    ("D'accord.",        "medium", "-2%"),
    ("Compris.",         "medium", "medium"),
    ("Entendu.",         "medium", "-3%"),
    ("C'est noté.",      "medium", "-2%"),
    ("Noté.",            "medium", "medium"),
    ("D'accord, merci.", "medium", "-2%"),
    ("Je note.",         "-5%",    "-3%"),
    ("Je vois.",         "-5%",    "-3%"),
]

# Message joué quand le patient sort du périmètre (sans relire toute la question médicale)
OUT_OF_SCOPE_MESSAGE = (
    "Je ne peux pas répondre à ce sujet : mon rôle est seulement de recueillir quelques informations "
    "sur votre sortie. "
)


def short_reprompt_after_out_of_scope(
    question_type: str, choices: Optional[List[str]] = None
) -> str:
    """Invite minimale après hors périmètre — pas de répétition du libellé long de la question."""
    t = (question_type or "yesno").lower()
    if t == "score":
        return "Donnez un chiffre entre zéro et dix."
    if t == "choice" and choices:
        opts = ", ".join(choices[:6])
        return f"Répondez par l'un de ces choix : {opts}."
    if t == "open":
        return "Répondez en une phrase courte."
    return "Répondez par oui ou par non."

# Préfixes joués avant de rejouer une question non comprise (Option 5)
RETRY_PREFIXES = [
    "Je répète.",
]

# Message joué avant la question suivante quand le max de retries est atteint (Option 3)
SKIP_MESSAGE = "Je passe à la suite."

# Message joué quand le patient ne sait pas répondre (réponse valide mais indéterminée)
NSP_MESSAGE = "Je comprends, pas de souci. Passons à la suite."

# Quand aucune question active n'est configurée en base
NO_ACTIVE_QUESTIONS_MESSAGE = (
    "Aucune question n'est disponible pour ce suivi. Au revoir."
)
