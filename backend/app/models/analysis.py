"""
Modèle Analysis pour les analyses IA des appels
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.call import Call
    from app.models.report import Report
    from app.models.transcription import Transcription


class Analysis(Base):
    """Modèle pour les analyses IA des conversations téléphoniques"""
    
    __tablename__ = "analyses"
    
    # Colonnes
    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
    
    # Relations
    call_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    transcription_id: Mapped[Optional[UUID]] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("transcriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Résultats du questionnaire médical de suivi postopératoire
    # 1. Douleur
    has_pain: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Présence de douleur",
    )
    pain_level: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Niveau de douleur de 0 à 10",
    )
    pain_relieved: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Douleur soulagée par les anti-douleur",
    )

    # 2. Alimentation
    eating_normally: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Mange normalement",
    )
    eating_difficulty_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Score de difficulté à manger (0-10)",
    )
    drinking_possible: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Peut boire normalement",
    )

    # 3. Nausées / Vomissements
    has_nausea: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Présence de nausées ou vomissements",
    )
    nausea_severity_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Score de sévérité des nausées (0-10)",
    )
    blood_in_vomit: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Sang dans les vomissements",
    )

    # 4. Maux de tête
    has_headache: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Présence de maux de tête",
    )
    headache_level: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Niveau des maux de tête (0-10)",
    )

    # 5. Saignements
    has_bleeding: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Présence de saignements",
    )
    bleeding_abundance_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Score d'abondance des saignements (0-10)",
    )
    bleeding_stopped: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Saignements arrêtés",
    )
    infection_signs: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Signes d'infection (suintement, rougeur)",
    )

    # 6. Contact médical
    contacted_emergency: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="A contacté médecin ou urgences",
    )
    emergency_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Raison du contact médical",
    )

    # 7. Consignes postopératoires
    understands_instructions: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="Comprend les consignes postopératoires",
    )
    instruction_doubts: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Doutes sur les consignes",
    )

    # Anciens champs (compatibilité ascendante - à déprécier progressivement)
    pain_location: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="[DEPRECATED] Localisation de la douleur",
    )
    pain_description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="[DEPRECATED] Description détaillée de la douleur",
    )
    has_fever: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="[DEPRECATED] Fièvre",
    )
    fever_temperature: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="[DEPRECATED] Température en degrés Celsius",
    )
    fever_duration: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="[DEPRECATED] Durée de la fièvre",
    )
    takes_medication: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="[DEPRECATED] Prend des médicaments",
    )
    medication_regularity: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="[DEPRECATED] Régularité de prise des médicaments",
    )
    medication_issues: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="[DEPRECATED] Problèmes avec les médicaments",
    )
    moral_state: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="[DEPRECATED] État moral de 1 (très bas) à 5 (très bien)",
    )
    moral_description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="[DEPRECATED] Description de l'état moral",
    )
    
    # Analyse IA
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Résumé de l'analyse",
    )
    
    alerts: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Alertes détectées [{type, severity, message, action}]",
    )
    
    recommendations: Mapped[Optional[List[str]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Recommandations médicales",
    )
    
    risk_score: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        index=True,
        comment="Score de risque global de 0 à 10",
    )
    
    # Métadonnées IA
    model_used: Mapped[str] = mapped_column(
        String(50),
        default="llama3.1:8b",
        nullable=False,
    )
    processing_time: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Temps de traitement en secondes",
    )
    confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Confiance de l'analyse (0.0 à 1.0)",
    )
    
    # Données brutes
    raw_response: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Réponse brute de l'IA",
    )
    
    # Métadonnées
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    # Relations ORM
    call: Mapped["Call"] = relationship(
        "Call",
        back_populates="analysis",
    )
    transcription: Mapped[Optional["Transcription"]] = relationship(
        "Transcription",
        back_populates="analysis",
    )
    reports: Mapped[List["Report"]] = relationship(
        "Report",
        back_populates="analysis",
        cascade="all, delete-orphan",
    )
    
    def __repr__(self) -> str:
        return f"<Analysis {self.id} - Risk: {self.risk_score}/10>"
    
    def __str__(self) -> str:
        return f"Analyse de l'appel {self.call_id}"
    
    @property
    def has_critical_alerts(self) -> bool:
        """Vérifie s'il y a des alertes critiques"""
        if not self.alerts:
            return False
        return any(alert.get("severity") == "urgent" for alert in self.alerts)
    
    @property
    def has_warnings(self) -> bool:
        """Vérifie s'il y a des avertissements"""
        if not self.alerts:
            return False
        return any(alert.get("severity") == "warning" for alert in self.alerts)
    
    @property
    def alert_count(self) -> int:
        """Retourne le nombre d'alertes"""
        return len(self.alerts) if self.alerts else 0
    
    @property
    def is_high_risk(self) -> bool:
        """Vérifie si le patient est à haut risque"""
        return self.risk_score >= 7
    
    @property
    def requires_medical_attention(self) -> bool:
        """Vérifie si une attention médicale est requise"""
        return (
            self.has_critical_alerts
            or self.risk_score >= 8
            or (self.fever_temperature and self.fever_temperature >= 38.5)
            or (self.pain_level and self.pain_level >= 8)
        )
    
    @property
    def medication_compliance_score(self) -> Optional[int]:
        """Calcule un score de compliance médicamenteuse"""
        if self.takes_medication is None:
            return None
        if not self.takes_medication:
            return 0
        if self.medication_regularity == "toujours":
            return 10
        elif self.medication_regularity == "souvent":
            return 7
        elif self.medication_regularity == "parfois":
            return 4
        else:
            return 2
    
    def get_critical_alerts(self) -> List[Dict[str, Any]]:
        """Retourne uniquement les alertes critiques"""
        if not self.alerts:
            return []
        return [a for a in self.alerts if a.get("severity") == "urgent"]
    
    def get_recommendations_by_priority(self) -> List[str]:
        """Retourne les recommandations triées par priorité"""
        if not self.recommendations:
            return []
        # TODO: Implémenter une logique de tri par priorité
        return self.recommendations

