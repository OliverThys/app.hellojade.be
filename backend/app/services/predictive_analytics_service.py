"""
Service d'analytics prédictifs pour détecter les tendances et prédire les risques
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.call import Call
from app.models.patient import Patient
from app.models.analysis import Analysis
from app.core.logging import get_logger

logger = get_logger(__name__)


class PredictiveAnalyticsService:
    """Service d'analytics prédictifs pour patients"""
    
    @staticmethod
    async def calculate_patient_trends(
        db: AsyncSession,
        patient_id: UUID,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Calcule les tendances d'évolution d'un patient sur les derniers jours
        
        Returns:
            Dict avec:
            - risk_score_trend: "increasing", "decreasing", "stable"
            - pain_trend: Évolution de la douleur
            - medication_compliance_trend: Évolution de la compliance
            - moral_state_trend: Évolution du moral
            - predicted_next_risk_score: Score de risque prédit
            - deterioration_signals: Signaux de dégradation détectés
        """
        # Récupérer les analyses des dernières semaines
        cutoff_date = datetime.now() - timedelta(days=days)
        
        stmt = (
            select(Analysis)
            .join(Call)
            .where(Call.patient_id == patient_id)
            .where(Analysis.created_at >= cutoff_date)
            .order_by(Analysis.created_at.desc())
        )
        result = await db.execute(stmt)
        analyses = result.scalars().all()
        
        if len(analyses) < 2:
            return {
                "risk_score_trend": "insufficient_data",
                "message": "Pas assez de données pour calculer les tendances",
            }
        
        # Analyser les tendances
        risk_scores = [a.risk_score for a in analyses[::-1]]  # Du plus ancien au plus récent
        pain_levels = [a.pain_level for a in analyses[::-1] if a.pain_level is not None]
        moral_states = [a.moral_state for a in analyses[::-1] if a.moral_state is not None]
        
        # Tendance du score de risque
        risk_trend = "stable"
        if len(risk_scores) >= 2:
            recent_avg = sum(risk_scores[-3:]) / min(3, len(risk_scores))
            older_avg = sum(risk_scores[:max(1, len(risk_scores)-3)]) / max(1, len(risk_scores)-3)
            
            if recent_avg > older_avg + 1:
                risk_trend = "increasing"
            elif recent_avg < older_avg - 1:
                risk_trend = "decreasing"
        
        # Prédiction du prochain score de risque (simple régression linéaire)
        predicted_next_risk = risk_scores[-1] if risk_scores else 0
        if len(risk_scores) >= 3:
            # Calcul simple de tendance
            recent_change = risk_scores[-1] - risk_scores[-2]
            predicted_next_risk = min(10, max(0, risk_scores[-1] + recent_change * 0.7))
        
        # Signaux de dégradation
        deterioration_signals = []
        
        # Vérifier augmentation de la douleur
        if len(pain_levels) >= 2:
            if pain_levels[-1] > pain_levels[0] + 2:
                deterioration_signals.append({
                    "type": "pain_increase",
                    "severity": "warning",
                    "message": f"Douleur en augmentation ({pain_levels[0]} → {pain_levels[-1]}/10)",
                })
        
        # Vérifier baisse du moral
        if len(moral_states) >= 2:
            if moral_states[-1] < moral_states[0] - 1:
                deterioration_signals.append({
                    "type": "moral_decline",
                    "severity": "warning",
                    "message": f"État moral en baisse ({moral_states[0]} → {moral_states[-1]}/5)",
                })
        
        # Vérifier non-compliance médicamenteuse croissante
        medication_issues = [a for a in analyses if a.medication_issues]
        if len(medication_issues) > len(analyses) * 0.5:
            deterioration_signals.append({
                "type": "medication_compliance",
                "severity": "warning",
                "message": "Problèmes récurrents de compliance médicamenteuse",
            })
        
        # Tendance compliance
        compliance_scores = []
        for a in analyses:
            if a.takes_medication:
                if a.medication_regularity == "toujours":
                    compliance_scores.append(10)
                elif a.medication_regularity == "souvent":
                    compliance_scores.append(7)
                elif a.medication_regularity == "parfois":
                    compliance_scores.append(4)
                else:
                    compliance_scores.append(2)
            else:
                compliance_scores.append(0)
        
        compliance_trend = "stable"
        if len(compliance_scores) >= 2:
            recent_compliance = sum(compliance_scores[-3:]) / min(3, len(compliance_scores))
            older_compliance = sum(compliance_scores[:max(1, len(compliance_scores)-3)]) / max(1, len(compliance_scores)-3)
            
            if recent_compliance < older_compliance - 2:
                compliance_trend = "decreasing"
            elif recent_compliance > older_compliance + 2:
                compliance_trend = "improving"
        
        return {
            "risk_score_trend": risk_trend,
            "pain_trend": "increasing" if len(pain_levels) >= 2 and pain_levels[-1] > pain_levels[0] + 1 else "stable",
            "medication_compliance_trend": compliance_trend,
            "moral_state_trend": "decreasing" if len(moral_states) >= 2 and moral_states[-1] < moral_states[0] - 1 else "stable",
            "predicted_next_risk_score": round(predicted_next_risk, 1),
            "deterioration_signals": deterioration_signals,
            "analysis_count": len(analyses),
            "days_analyzed": days,
        }
    
    @staticmethod
    async def detect_early_warning_signals(
        db: AsyncSession,
        patient_id: UUID
    ) -> List[Dict[str, Any]]:
        """
        Détecte les signaux d'alerte précoce pour un patient
        
        Returns:
            Liste des signaux d'alerte détectés
        """
        signals = []
        
        # Récupérer les 2 dernières analyses
        stmt = (
            select(Analysis)
            .join(Call)
            .where(Call.patient_id == patient_id)
            .order_by(Analysis.created_at.desc())
            .limit(2)
        )
        result = await db.execute(stmt)
        recent_analyses = result.scalars().all()
        
        if len(recent_analyses) < 1:
            return signals
        
        latest = recent_analyses[0]
        
        # Détection de signaux d'alerte
        # 1. Douleur en augmentation rapide
        if len(recent_analyses) >= 2:
            prev = recent_analyses[1]
            if latest.pain_level and prev.pain_level:
                if latest.pain_level > prev.pain_level + 3:
                    signals.append({
                        "type": "rapid_pain_increase",
                        "severity": "urgent",
                        "message": f"Douleur en augmentation rapide ({prev.pain_level} → {latest.pain_level}/10)",
                        "action": "Évaluation médicale recommandée",
                    })
        
        # 2. Fièvre nouvelle ou persistante
        if latest.has_fever:
            if latest.fever_temperature and latest.fever_temperature >= 38.5:
                signals.append({
                    "type": "high_fever",
                    "severity": "urgent",
                    "message": f"Fièvre élevée détectée ({latest.fever_temperature}°C)",
                    "action": "Surveillance de la température, contact médical si persistance",
                })
        
        # 3. Dégradation rapide du moral
        if len(recent_analyses) >= 2:
            prev = recent_analyses[1]
            if latest.moral_state and prev.moral_state:
                if latest.moral_state < prev.moral_state - 2:
                    signals.append({
                        "type": "rapid_moral_decline",
                        "severity": "warning",
                        "message": f"Dégradation rapide de l'état moral ({prev.moral_state} → {latest.moral_state}/5)",
                        "action": "Soutien psychologique recommandé",
                    })
        
        # 4. Non-compliance médicamenteuse avec symptômes
        if latest.medication_issues and latest.medication_regularity in ["parfois", "rarement"]:
            if latest.pain_level and latest.pain_level > 5:
                signals.append({
                    "type": "medication_noncompliance_with_symptoms",
                    "severity": "warning",
                    "message": "Non-compliance médicamenteuse avec symptômes persistants",
                    "action": "Renforcement de l'éducation thérapeutique",
                })
        
        # 5. Score de risque proche du seuil critique
        if latest.risk_score >= 8:
            signals.append({
                "type": "high_risk_score",
                "severity": "urgent",
                "message": f"Score de risque élevé ({latest.risk_score}/10)",
                "action": "Surveillance rapprochée recommandée",
            })
        
        return signals
    
    @staticmethod
    async def predict_readmission_risk(
        db: AsyncSession,
        patient_id: UUID
    ) -> Dict[str, Any]:
        """
        Prédit le risque de réadmission hospitalière
        
        Returns:
            Dict avec:
            - readmission_risk_score: Score de 0 à 10
            - readmission_probability: Probabilité en %
            - risk_factors: Facteurs de risque identifiés
            - recommended_actions: Actions recommandées
        """
        patient = await db.get(Patient, patient_id)
        if not patient:
            return {"error": "Patient non trouvé"}
        
        risk_factors = []
        risk_score = 0
        
        # Facteur 1: Score de risque actuel élevé
        if patient.risk_score >= 7:
            risk_score += 3
            risk_factors.append({
                "factor": "Score de risque actuel élevé",
                "weight": "high",
            })
        
        # Facteur 2: Dégradation récente
        trends = await PredictiveAnalyticsService.calculate_patient_trends(db, patient_id, days=14)
        if trends.get("risk_score_trend") == "increasing":
            risk_score += 2
            risk_factors.append({
                "factor": "Dégradation récente de l'état",
                "weight": "medium",
            })
        
        # Facteur 3: Non-compliance médicamenteuse
        stmt = (
            select(Analysis)
            .join(Call)
            .where(Call.patient_id == patient_id)
            .order_by(Analysis.created_at.desc())
            .limit(3)
        )
        result = await db.execute(stmt)
        recent_analyses = result.scalars().all()
        
        non_compliance_count = sum(
            1 for a in recent_analyses
            if a.medication_regularity in ["parfois", "rarement"] or not a.takes_medication
        )
        if non_compliance_count >= 2:
            risk_score += 2
            risk_factors.append({
                "factor": "Non-compliance médicamenteuse",
                "weight": "medium",
            })
        
        # Facteur 4: Symptômes persistants
        if recent_analyses:
            latest = recent_analyses[0]
            if latest.pain_level and latest.pain_level >= 6:
                risk_score += 1
                risk_factors.append({
                    "factor": "Douleurs persistantes",
                    "weight": "low",
                })
            if latest.has_fever:
                risk_score += 1
                risk_factors.append({
                    "factor": "Fièvre présente",
                    "weight": "low",
                })
        
        # Facteur 5: Détresse émotionnelle
        if recent_analyses and recent_analyses[0].moral_state:
            if recent_analyses[0].moral_state <= 2:
                risk_score += 1
                risk_factors.append({
                    "factor": "Détresse émotionnelle importante",
                    "weight": "low",
                })
        
        # Calculer la probabilité (approximative)
        probability = min(95, max(5, risk_score * 10))
        
        # Actions recommandées
        recommended_actions = []
        if risk_score >= 7:
            recommended_actions.append("Surveillance rapprochée (appels quotidiens)")
            recommended_actions.append("Évaluation médicale préventive")
        elif risk_score >= 4:
            recommended_actions.append("Surveillance renforcée (appels 2-3x par semaine)")
        else:
            recommended_actions.append("Surveillance standard")
        
        return {
            "readmission_risk_score": min(10, risk_score),
            "readmission_probability": round(probability, 1),
            "risk_factors": risk_factors,
            "recommended_actions": recommended_actions,
            "calculated_at": datetime.now().isoformat(),
        }
    
    @staticmethod
    async def get_patient_evolution_timeline(
        db: AsyncSession,
        patient_id: UUID,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Génère une timeline de l'évolution du patient
        
        Returns:
            Liste des points de données pour la timeline
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        
        stmt = (
            select(Analysis, Call)
            .join(Call)
            .where(Call.patient_id == patient_id)
            .where(Analysis.created_at >= cutoff_date)
            .order_by(Analysis.created_at.asc())
        )
        result = await db.execute(stmt)
        analyses_with_calls = result.all()
        
        timeline = []
        for analysis, call in analyses_with_calls:
            timeline.append({
                "date": analysis.created_at.isoformat(),
                "call_id": str(call.id),
                "risk_score": analysis.risk_score,
                "pain_level": analysis.pain_level,
                "moral_state": analysis.moral_state,
                "has_fever": analysis.has_fever,
                "fever_temperature": analysis.fever_temperature,
                "medication_compliance": (
                    "high" if analysis.medication_regularity == "toujours"
                    else "medium" if analysis.medication_regularity == "souvent"
                    else "low" if analysis.medication_regularity in ["parfois", "rarement"]
                    else "none"
                ),
                "alerts_count": len(analysis.alerts) if analysis.alerts else 0,
            })
        
        return timeline
    
    @staticmethod
    async def get_cohort_comparison(
        db: AsyncSession,
        patient_id: UUID
    ) -> Dict[str, Any]:
        """
        Compare un patient avec des patients similaires (cohorte)
        
        Returns:
            Comparaison avec la cohorte
        """
        patient = await db.get(Patient, patient_id)
        if not patient:
            return {"error": "Patient non trouvé"}
        
        # Trouver des patients similaires (même service, diagnostic proche, etc.)
        stmt = select(Patient).where(
            Patient.service_hospitalisation == patient.service_hospitalisation,
            Patient.id != patient_id,
            Patient.status == "actif",
        ).limit(10)
        
        result = await db.execute(stmt)
        similar_patients = result.scalars().all()
        
        if not similar_patients:
            return {
                "message": "Pas de patients similaires trouvés",
                "cohort_size": 0,
            }
        
        # Calculer les moyennes de la cohorte
        cohort_risk_scores = [p.risk_score for p in similar_patients]
        cohort_avg_risk = sum(cohort_risk_scores) / len(cohort_risk_scores) if cohort_risk_scores else 0
        
        # Comparer avec le patient
        comparison = "better" if patient.risk_score < cohort_avg_risk else "worse" if patient.risk_score > cohort_avg_risk else "similar"
        
        return {
            "patient_risk_score": patient.risk_score,
            "cohort_avg_risk_score": round(cohort_avg_risk, 1),
            "cohort_size": len(similar_patients),
            "comparison": comparison,
            "difference": round(patient.risk_score - cohort_avg_risk, 1),
        }


# Instance globale
predictive_analytics_service = PredictiveAnalyticsService()

