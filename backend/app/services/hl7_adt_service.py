"""
Service de parsing HL7 v2.2 ADT pour l'import de patients depuis Mirth (Epicura).

Traite les messages ADT (Admission/Discharge/Transfer) envoyés par Mirth :
- ADT^A03 : Sortie du patient (principal use case)
- ADT^A08 : Mise à jour des informations patient

Les messages HL7 v2.2 utilisent le format pipe-delimited (ER7).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


class HL7ParseError(Exception):
    """Erreur lors du parsing d'un message HL7"""
    pass


class HL7Message:
    """Représentation simple d'un message HL7 v2.2 pipe-delimited."""

    def __init__(self, raw: str) -> None:
        self.raw = raw.strip()
        self.segments: Dict[str, List[List[str]]] = {}
        self._parse()

    def _parse(self) -> None:
        """Parse les segments du message HL7."""
        # HL7 utilise \r comme séparateur de segments
        lines = self.raw.replace("\n", "\r").split("\r")
        lines = [line.strip() for line in lines if line.strip()]

        if not lines:
            raise HL7ParseError("Message HL7 vide")

        # Vérifier le segment MSH
        if not lines[0].startswith("MSH"):
            raise HL7ParseError("Le message ne commence pas par MSH")

        for line in lines:
            # Le séparateur de champs est | (défini dans MSH.1)
            fields = line.split("|")
            segment_name = fields[0]

            if segment_name not in self.segments:
                self.segments[segment_name] = []
            self.segments[segment_name].append(fields)

    def get_segment(self, name: str) -> Optional[List[str]]:
        """Retourne le premier segment du type donné."""
        segments = self.segments.get(name)
        return segments[0] if segments else None

    def get_field(self, segment: str, index: int, component: int = 0) -> str:
        """
        Récupère un champ d'un segment.

        Pour MSH, l'index est décalé de +1 car MSH.1 = | (séparateur).
        Les composants sont séparés par ^.
        """
        seg = self.get_segment(segment)
        if not seg:
            return ""

        # MSH a un décalage : MSH|^~\\&|... → fields[0]="MSH", fields[1]="^~\\&"
        # Donc MSH.3 = fields[2], MSH.9 = fields[8]
        # Pour les autres segments : PID.3 = fields[3]
        if segment == "MSH":
            idx = index - 1  # MSH.1 = fields[1] → séparateur
        else:
            idx = index

        if idx < 0 or idx >= len(seg):
            return ""

        value = seg[idx]

        if component > 0:
            components = value.split("^")
            if component <= len(components):
                return components[component - 1]
            return ""

        return value

    @property
    def message_type(self) -> str:
        """Retourne le type de message (ex: ADT^A03)."""
        return self.get_field("MSH", 9)

    @property
    def event_type(self) -> str:
        """Retourne l'événement (ex: A03)."""
        msg_type = self.message_type
        parts = msg_type.split("^")
        return parts[1] if len(parts) > 1 else ""

    @property
    def version(self) -> str:
        """Retourne la version HL7."""
        return self.get_field("MSH", 12)


def parse_adt_message(raw_message: str) -> Dict[str, Any]:
    """
    Parse un message HL7 ADT et extrait les données patient.

    Retourne un dict avec les champs suivants :
    - event_type: str (A03, A08, etc.)
    - patient: dict avec les données PID
    - visit: dict avec les données PV1
    """
    msg = HL7Message(raw_message)

    event = msg.event_type
    if not event:
        raise HL7ParseError("Type d'événement manquant dans MSH.9")

    # --- PID : Patient Identification ---
    # PID.2 : Patient ID (externe)
    # PID.3 : Patient Identifier List (numéro dossier)
    # PID.5 : Patient Name (nom^prénom)
    # PID.7 : Date of Birth (YYYYMMDD)
    # PID.8 : Sex (M/F)
    # PID.11 : Address
    # PID.13 : Phone Number - Home

    patient_id_external = msg.get_field("PID", 2)
    numero_dossier = msg.get_field("PID", 3, component=1) or msg.get_field("PID", 3)
    patient_name = msg.get_field("PID", 5)
    nom = patient_name.split("^")[0] if patient_name else ""
    prenom = patient_name.split("^")[1] if "^" in patient_name else ""
    date_naissance_raw = msg.get_field("PID", 7)
    sexe = msg.get_field("PID", 8)
    address = msg.get_field("PID", 11)
    telephone = msg.get_field("PID", 13, component=1) or msg.get_field("PID", 13)

    # Nettoyage téléphone
    telephone = _clean_phone(telephone)

    # Parse date de naissance
    date_naissance = _parse_hl7_date(date_naissance_raw)

    # Parse adresse (composants: rue^ville^code_postal^...)
    adresse_parts = address.split("^") if address else []
    adresse = adresse_parts[0] if len(adresse_parts) > 0 else None
    ville = adresse_parts[2] if len(adresse_parts) > 2 else None
    code_postal = adresse_parts[4] if len(adresse_parts) > 4 else None

    # --- PV1 : Patient Visit ---
    # PV1.2 : Patient Class (I=Inpatient, O=Outpatient)
    # PV1.3 : Assigned Patient Location (service)
    # PV1.7 : Attending Doctor
    # PV1.19 : Visit Number (séjour^visite chez Epicura)
    # PV1.44 : Admit Date/Time
    # PV1.45 : Discharge Date/Time

    service_code = msg.get_field("PV1", 3, component=1) or msg.get_field("PV1", 3)
    medecin = msg.get_field("PV1", 7)
    medecin_nom = medecin.split("^")[1] if "^" in medecin else medecin

    pv1_19 = msg.get_field("PV1", 19)
    pv1_19_parts = pv1_19.split("^") if pv1_19 else []
    sejour_id = pv1_19_parts[0] if len(pv1_19_parts) > 0 else ""
    visite_id = pv1_19_parts[1] if len(pv1_19_parts) > 1 else ""

    date_admission = _parse_hl7_datetime(msg.get_field("PV1", 44))
    date_sortie = _parse_hl7_datetime(msg.get_field("PV1", 45))

    return {
        "event_type": event,
        "hl7_version": msg.version,
        "patient": {
            "oracle_patient_id": patient_id_external,
            "numero_dossier": numero_dossier,
            "nom": nom,
            "prenom": prenom,
            "telephone": telephone,
            "date_naissance": date_naissance,
            "sexe": sexe[:1].upper() if sexe else None,
            "adresse": adresse,
            "ville": ville,
            "code_postal": code_postal,
        },
        "visit": {
            "service_code": service_code,
            "sejour_id": sejour_id,
            "visite_id": visite_id,
            "medecin_responsable": medecin_nom,
            "date_admission": date_admission,
            "date_sortie": date_sortie,
        },
    }


def build_ack_message(
    original_msg: str,
    ack_code: str = "AA",
    error_msg: str = "",
) -> str:
    """
    Construit un message ACK HL7 en réponse à un message reçu.

    ack_code :
    - AA = Application Accept
    - AE = Application Error
    - AR = Application Reject
    """
    try:
        msg = HL7Message(original_msg)
        sending_app = msg.get_field("MSH", 3)
        sending_facility = msg.get_field("MSH", 4)
        receiving_app = msg.get_field("MSH", 5)
        receiving_facility = msg.get_field("MSH", 6)
        control_id = msg.get_field("MSH", 10)
        version = msg.get_field("MSH", 12) or "2.2"
    except Exception:
        sending_app = receiving_app = ""
        sending_facility = receiving_facility = ""
        control_id = "UNKNOWN"
        version = "2.2"

    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")

    msh = "|".join([
        "MSH",
        "^~\\&",
        receiving_app or "HELLOJADE",
        receiving_facility or "EPICURA",
        sending_app,
        sending_facility,
        ts,
        "",
        "ACK",
        ts,
        "P",
        version,
    ])

    msa_fields = ["MSA", ack_code, control_id]
    if error_msg:
        msa_fields.append(error_msg)
    msa = "|".join(msa_fields)

    return f"{msh}\r{msa}\r"


def _clean_phone(phone: str) -> Optional[str]:
    """Nettoie un numéro de téléphone."""
    if not phone:
        return None
    # Supprimer caractères non numériques sauf +
    cleaned = "".join(c for c in phone if c.isdigit() or c == "+")
    if not cleaned:
        return None
    # Ajouter +32 si numéro belge sans indicatif
    if cleaned.startswith("0") and len(cleaned) >= 9:
        cleaned = "+32" + cleaned[1:]
    elif not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def _parse_hl7_date(date_str: str) -> Optional[datetime]:
    """Parse une date HL7 (YYYYMMDD)."""
    if not date_str or len(date_str) < 8:
        return None
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d")
    except ValueError:
        return None


def _parse_hl7_datetime(dt_str: str) -> Optional[datetime]:
    """Parse un datetime HL7 (YYYYMMDDHHMMSS)."""
    if not dt_str:
        return None
    try:
        if len(dt_str) >= 14:
            return datetime.strptime(dt_str[:14], "%Y%m%d%H%M%S")
        elif len(dt_str) >= 8:
            return datetime.strptime(dt_str[:8], "%Y%m%d")
    except ValueError:
        pass
    return None
