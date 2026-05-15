"""
Service HL7 v2.2 spécifique à Epicura pour l'émission de messages ORU^R01
avec encapsulation du PDF en base64.

Génération du message + transport vers Mirth (HTTP POST ou SFTP).
"""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EpicuraHL7Service:
    """
    Génération d'un message HL7 ORU^R01 v2.2 à partir :
    - des métadonnées d'appel
    - des données patient
    - des informations d'analyse
    - du chemin vers le PDF généré
    """

    def __init__(self) -> None:
        # Répertoire où déposer les messages HL7 générés
        self.hl7_out_dir = Path(settings.REPORTS_PATH) / "hl7"
        self.hl7_out_dir.mkdir(parents=True, exist_ok=True)

    def _format_ts(self, dt: datetime | None) -> str:
        """Formate un datetime en timestamp HL7 (YYYYMMDDHHMMSS)."""
        if not dt:
            dt = datetime.utcnow()
        return dt.strftime("%Y%m%d%H%M%S")

    def _build_msh_segment(self) -> str:
        """
        Construit le segment MSH minimal pour ORU^R01.

        Remarque : les champs MSH-3/4/5/6/7 pourront être ajustés avec
        l'équipe Epicura si besoin.
        """
        sending_app = "HELLOJADE"
        sending_facility = "EPICURA"
        receiving_app = "EPICURA_SI"
        receiving_facility = "EPICURA"
        timestamp = self._format_ts(datetime.utcnow())
        message_type = "ORU^R01"
        message_control_id = timestamp  # simplifié
        processing_id = "P"
        version_id = "2.2"

        fields = [
            "MSH",
            "^~\\&",
            sending_app,
            sending_facility,
            receiving_app,
            receiving_facility,
            timestamp,
            "",
            message_type,
            message_control_id,
            processing_id,
            version_id,
        ]
        return "|".join(fields)

    def _build_pid_segment(self, patient_data: Dict[str, Any]) -> str:
        """
        Construit un segment PID minimal.

        Les champs peuvent être enrichis ultérieurement suivant le guide HL7 local.
        """
        patient_id = patient_data.get("numero_dossier") or ""
        last_name = patient_data.get("nom") or ""
        first_name = patient_data.get("prenom") or ""
        phone = patient_data.get("telephone") or ""

        name = f"{last_name}^{first_name}"

        fields = [
            "PID",
            "1",
            patient_id,
            patient_id,
            "",
            name,
            "",
            "",
            "",
            phone,
        ]
        return "|".join(fields)

    def _build_pv1_segment(self, call_data: Dict[str, Any], patient_data: Dict[str, Any]) -> str:
        """
        Construit un segment PV1 avec la particularité Epicura:
        - PV1.19.1 = séjour
        - PV1.19.2 = visite (incrément)
        """
        # Ces informations devront être enrichies si Epicura fournit
        # des identifiants de séjour/visite spécifiques.
        sejour_id = patient_data.get("sejour_id", "") or ""
        visite_id = patient_data.get("visite_id", "") or ""

        pv119 = f"{sejour_id}^{visite_id}" if sejour_id or visite_id else ""

        fields = [
            "PV1",
            "1",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            pv119,
        ]
        return "|".join(fields)

    def _build_obr_segment(self, call_data: Dict[str, Any]) -> str:
        """
        Segment OBR pour l'observation (rapport HelloJADE).
        """
        call_id = call_data.get("id") or ""
        # On pourrait utiliser un code interne spécifique pour HelloJADE
        universal_service_id = "HELLOJADE^RAPPORT_SUIVI_POST_HOSPI"
        observation_datetime = self._format_ts(
            call_data.get("created_at_dt")  # datetime si fourni
        )

        fields = [
            "OBR",
            "1",
            call_id,
            call_id,
            universal_service_id,
            "",
            observation_datetime,
        ]
        return "|".join(fields)

    def _build_obx_pdf_segment(self, pdf_path: str) -> str:
        """
        Segment OBX contenant le PDF encodé en base64.

        Utilisation d'un type de données ED (Encapsulated Data) classique:
        OBX-5 = ^PDF^Base64^{data}
        """
        file = Path(pdf_path)
        if not file.exists():
            raise FileNotFoundError(f"PDF introuvable pour HL7 ORU: {pdf_path}")

        pdf_bytes = file.read_bytes()
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

        # Type de données ED : ^PDF^Base64^{data}
        ed_value = f"^PDF^Base64^{pdf_b64}"

        fields = [
            "OBX",
            "1",
            "ED",
            "RAPPORT_PDF^HELLOJADE",
            "",
            ed_value,
            "",
            "",
            "",
            "",
            "F",  # Observation finale
        ]
        return "|".join(fields)

    def generate_oru_message(
        self,
        call_data: Dict[str, Any],
        patient_data: Dict[str, Any],
        pdf_path: str,
    ) -> str:
        """
        Construit et sauvegarde un message ORU^R01 HL7 v2.2.

        Retourne le chemin du fichier .hl7 généré.
        """
        # Normaliser/compléter certaines données
        if isinstance(call_data.get("created_at"), str):
            try:
                call_data["created_at_dt"] = datetime.fromisoformat(
                    call_data["created_at"].replace("Z", "+00:00")
                )
            except Exception:
                call_data["created_at_dt"] = datetime.utcnow()

        segments = [
            self._build_msh_segment(),
            self._build_pid_segment(patient_data),
            self._build_pv1_segment(call_data, patient_data),
            self._build_obr_segment(call_data),
            self._build_obx_pdf_segment(pdf_path),
        ]

        message = "\r".join(segments) + "\r"

        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        call_id = call_data.get("id", "unknown")
        filename = f"oru_{call_id}_{ts}.hl7"
        out_path = self.hl7_out_dir / filename

        out_path.write_text(message, encoding="utf-8")

        logger.info(f"Message HL7 ORU généré: {out_path}")

        return str(out_path)

    # ══════════════════════════════════════════════════════════
    # TRANSPORT vers Mirth
    # ══════════════════════════════════════════════════════════

    async def send_oru(self, hl7_file_path: str) -> Dict[str, Any]:
        """
        Envoie un message ORU vers Mirth selon le transport configuré.

        Retourne {"success": bool, "transport": str, "detail": str}
        """
        transport = settings.MIRTH_TRANSPORT.lower()

        if transport == "http":
            return await self._send_oru_http(hl7_file_path)
        elif transport == "sftp":
            return self._send_oru_sftp(hl7_file_path)
        else:
            logger.warning(f"Transport Mirth non configuré ({transport}), message HL7 conservé localement")
            return {"success": True, "transport": "local", "detail": f"Fichier local: {hl7_file_path}"}

    async def _send_oru_http(self, hl7_file_path: str) -> Dict[str, Any]:
        """Envoie le message HL7 via HTTP POST vers Mirth HTTP Listener."""
        url = settings.MIRTH_HTTP_URL
        if not url:
            logger.warning("MIRTH_HTTP_URL non configuré, envoi ORU impossible")
            return {"success": False, "transport": "http", "detail": "MIRTH_HTTP_URL not configured"}

        file_path = Path(hl7_file_path)
        if not file_path.exists():
            return {"success": False, "transport": "http", "detail": f"Fichier introuvable: {hl7_file_path}"}

        message = file_path.read_text(encoding="utf-8")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    content=message,
                    headers={
                        "Content-Type": "x-application/hl7-v2+er7",
                        "Accept": "x-application/hl7-v2+er7",
                    },
                )

            if response.status_code < 300:
                logger.info(f"ORU envoyé via HTTP vers Mirth: {url} (status {response.status_code})")
                return {
                    "success": True,
                    "transport": "http",
                    "detail": f"HTTP {response.status_code}",
                    "mirth_response": response.text[:500],
                }
            else:
                logger.error(f"Erreur HTTP Mirth: {response.status_code} - {response.text[:200]}")
                return {
                    "success": False,
                    "transport": "http",
                    "detail": f"HTTP {response.status_code}: {response.text[:200]}",
                }

        except httpx.TimeoutException:
            logger.error(f"Timeout lors de l'envoi ORU vers Mirth ({url})")
            return {"success": False, "transport": "http", "detail": "Connection timeout"}
        except Exception as e:
            logger.error(f"Erreur envoi ORU HTTP: {e}")
            return {"success": False, "transport": "http", "detail": str(e)}

    def _send_oru_sftp(self, hl7_file_path: str) -> Dict[str, Any]:
        """Envoie le message HL7 via SFTP (dépôt de fichier)."""
        host = settings.MIRTH_SFTP_HOST
        if not host:
            logger.warning("MIRTH_SFTP_HOST non configuré, envoi ORU impossible")
            return {"success": False, "transport": "sftp", "detail": "MIRTH_SFTP_HOST not configured"}

        file_path = Path(hl7_file_path)
        if not file_path.exists():
            return {"success": False, "transport": "sftp", "detail": f"Fichier introuvable: {hl7_file_path}"}

        try:
            import paramiko

            transport = paramiko.Transport((host, settings.MIRTH_SFTP_PORT))
            transport.connect(
                username=settings.MIRTH_SFTP_USER,
                password=settings.MIRTH_SFTP_PASSWORD,
            )
            sftp = paramiko.SFTPClient.from_transport(transport)

            remote_path = f"{settings.MIRTH_SFTP_PATH}/{file_path.name}"
            sftp.put(str(file_path), remote_path)

            sftp.close()
            transport.close()

            logger.info(f"ORU envoyé via SFTP vers {host}:{remote_path}")
            return {
                "success": True,
                "transport": "sftp",
                "detail": f"Uploaded to {host}:{remote_path}",
            }

        except ImportError:
            logger.error("paramiko non installé, impossible d'utiliser SFTP")
            return {"success": False, "transport": "sftp", "detail": "paramiko not installed"}
        except Exception as e:
            logger.error(f"Erreur envoi ORU SFTP: {e}")
            return {"success": False, "transport": "sftp", "detail": str(e)}


epicura_hl7_service = EpicuraHL7Service()

