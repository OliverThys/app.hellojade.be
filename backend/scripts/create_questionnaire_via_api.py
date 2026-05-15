#!/usr/bin/env python3
"""
Crée un questionnaire via les mêmes routes HTTP que l'application (admin).

Aucun accès direct à la base : uniquement l'API publique.

Authentification (obligatoire, rôle admin) :
  - HELLOJADE_ACCESS_TOKEN ou --access-token
  - ou HELLOJADE_REFRESH_TOKEN / --refresh-token → POST /api/v1/auth/refresh

Obtenir un jeton : après connexion SAML, copier access_token (ou refresh_token)
depuis le stockage du navigateur / l’URL de redirection.

Usage :
  set HELLOJADE_ACCESS_TOKEN=...
  python scripts/create_questionnaire_via_api.py --base-url https://hellojadeapp.local/api

  python scripts/create_questionnaire_via_api.py --base-url http://127.0.0.1:8000/api \\
    --refresh-token \"...\" --set-default
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional
from uuid import UUID

import httpx

# Corps identique au contrat QuestionnaireCreateDTO (frontend adminService.createQuestionnaire)
DEMO_QUESTIONNAIRE: Dict[str, Any] = {
    "name": "Questionnaire démo (via API)",
    "description": "Créé par script HTTP — mêmes routes que l'UI admin.",
    "questions": [
        {
            "question_id": "demo_etat_general",
            "text": "Depuis votre sortie, vous sentez-vous globalement bien ?",
            "type": "yesno",
            "order": 0,
            "is_active": True,
            "record_duration": 15,
            "alert_type": "clinical",
            "follow_ups": [
                {
                    "question_id": "demo_preciser",
                    "text": "Pouvez-vous préciser ce qui ne va pas, en quelques mots ?",
                    "type": "open",
                    "condition": "non",
                    "record_duration": 25,
                    "alert_type": "clinical",
                    "optional": False,
                    "is_active": True,
                }
            ],
        },
        {
            "question_id": "demo_traitement",
            "text": "Suivez-vous le traitement qui vous a été prescrit ?",
            "type": "yesno",
            "order": 1,
            "is_active": True,
            "record_duration": 15,
            "alert_type": "clinical",
            "follow_ups": [],
        },
    ],
    "messages": {
        "welcome": (
            "Bonjour, nous faisons un court suivi après votre sortie. "
            "Répondez simplement aux questions."
        ),
        "outro_normal": "Merci pour vos réponses. Bonne journée.",
        "outro_alert": "Nous transmettons votre situation à l'équipe soignante.",
        "outro_transfer_failed": "La mise en relation n'a pas abouti. Vous serez recontacté.",
    },
}


def _normalize_base(url: str) -> str:
    u = url.rstrip("/")
    if not u.endswith("/api"):
        u = f"{u}/api"
    return u


def _obtain_access_token(base: str, refresh: Optional[str]) -> str:
    if refresh:
        r = httpx.post(
            f"{base}/v1/auth/refresh",
            json={"refresh_token": refresh},
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()
        return str(data["access_token"])
    raise SystemExit(
        "Fournissez HELLOJADE_ACCESS_TOKEN / --access-token "
        "ou HELLOJADE_REFRESH_TOKEN / --refresh-token."
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Créer un questionnaire via l'API admin réelle.")
    p.add_argument(
        "--base-url",
        default=os.environ.get("HELLOJADE_API_BASE", "http://127.0.0.1:8000"),
        help="Origine API (avec ou sans suffixe /api), ex. https://hellojadeapp.local ou .../api",
    )
    p.add_argument("--access-token", default=os.environ.get("HELLOJADE_ACCESS_TOKEN"))
    p.add_argument("--refresh-token", default=os.environ.get("HELLOJADE_REFRESH_TOKEN"))
    p.add_argument(
        "--set-default",
        action="store_true",
        help="Après création, PUT /v1/admin/assignments/default (questionnaire par défaut)",
    )
    p.add_argument(
        "--care-unit-id",
        default=None,
        help="UUID d'une unité : PUT /v1/admin/assignments/{id} après création",
    )
    p.add_argument(
        "--payload-file",
        default=None,
        help="JSON fichier à envoyer au lieu du questionnaire démo intégré",
    )
    args = p.parse_args()

    base = _normalize_base(args.base_url)
    token = args.access_token
    if not token:
        token = _obtain_access_token(base, args.refresh_token)

    headers = {"Authorization": f"Bearer {token}"}

    if args.payload_file:
        with open(args.payload_file, encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = DEMO_QUESTIONNAIRE

    with httpx.Client(timeout=60.0) as client:
        cr = client.post(f"{base}/v1/admin/questionnaires", json=payload, headers=headers)
        if cr.status_code != 201:
            sys.stderr.write(cr.text)
            cr.raise_for_status()
        created = cr.json()
        qid = created["id"]
        print(json.dumps(created, indent=2, ensure_ascii=False))

        if args.set_default:
            ur = client.put(
                f"{base}/v1/admin/assignments/default",
                json={"questionnaire_id": qid},
                headers=headers,
            )
            if ur.status_code != 204:
                sys.stderr.write(ur.text)
                ur.raise_for_status()
            print("Affectation défaut →", qid, file=sys.stderr)

        if args.care_unit_id:
            UUID(args.care_unit_id)  # valide tôt
            ur = client.put(
                f"{base}/v1/admin/assignments/{args.care_unit_id}",
                json={"questionnaire_id": qid},
                headers=headers,
            )
            if ur.status_code != 204:
                sys.stderr.write(ur.text)
                ur.raise_for_status()
            print("Affectation unité", args.care_unit_id, "→", qid, file=sys.stderr)


if __name__ == "__main__":
    main()
