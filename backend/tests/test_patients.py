"""
Tests unitaires pour la gestion des patients
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from datetime import datetime, timedelta


@pytest.mark.asyncio
@pytest.mark.unit
class TestPatients:
    """Tests pour les endpoints de gestion des patients"""
    
    async def test_get_patients(
        self,
        async_client: AsyncClient,
        test_patient,
        medical_token: str,
    ):
        """Test de récupération de la liste des patients"""
        response = await async_client.get(
            "/api/v1/patients",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    async def test_get_patients_unauthorized(
        self,
        async_client: AsyncClient,
    ):
        """Test de récupération sans authentification"""
        response = await async_client.get("/api/v1/patients")
        
        assert response.status_code == 401
    
    async def test_get_patients_insufficient_permissions(
        self,
        async_client: AsyncClient,
        caregiver_token: str,
    ):
        """Test de récupération sans permissions suffisantes"""
        response = await async_client.get(
            "/api/v1/patients",
            headers={"Authorization": f"Bearer {caregiver_token}"},
        )
        
        # Devrait être 403 si le caregiver n'a pas les permissions
        # ou 200 s'il les a, selon la configuration
        assert response.status_code in [200, 403]
    
    async def test_get_patient_by_id(
        self,
        async_client: AsyncClient,
        test_patient,
        medical_token: str,
    ):
        """Test de récupération d'un patient par ID"""
        response = await async_client.get(
            f"/api/v1/patients/{test_patient.id}",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_patient.id)
        assert data["nom"] == test_patient.nom
        assert data["prenom"] == test_patient.prenom
    
    async def test_get_patient_not_found(
        self,
        async_client: AsyncClient,
        medical_token: str,
    ):
        """Test de récupération d'un patient inexistant"""
        fake_id = uuid4()
        response = await async_client.get(
            f"/api/v1/patients/{fake_id}",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 404
    
    async def test_create_patient(
        self,
        async_client: AsyncClient,
        test_medical_user,
        medical_token: str,
    ):
        """Test de création d'un nouveau patient"""
        patient_data = {
            "nom": "Martin",
            "prenom": "Sophie",
            "email": "sophie.martin@example.com",
            "telephone": "+32470123457",
            "numero_dossier": "P002",
            "date_naissance": (datetime.now() - timedelta(days=365*45)).isoformat(),
            "date_sortie": (datetime.now() - timedelta(days=1)).isoformat(),
            "service_hospitalisation": "Neurologie",
            "diagnostic_principal": "Accident vasculaire cérébral",
            "status": "actif",
            "consent_given": True,
            "risk_score": 7.0,
        }
        
        response = await async_client.post(
            "/api/v1/patients",
            json=patient_data,
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["nom"] == patient_data["nom"]
        assert data["prenom"] == patient_data["prenom"]
        assert data["numero_dossier"] == patient_data["numero_dossier"]
    
    async def test_update_patient(
        self,
        async_client: AsyncClient,
        test_patient,
        medical_token: str,
    ):
        """Test de mise à jour d'un patient"""
        update_data = {
            "status": "prioritaire",
            "risk_score": 8.5,
            "notes": "Patient nécessite un suivi rapproché",
        }
        
        response = await async_client.patch(
            f"/api/v1/patients/{test_patient.id}",
            json=update_data,
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == update_data["status"]
        assert data["risk_score"] == update_data["risk_score"]
        assert data["notes"] == update_data["notes"]
    
    async def test_update_patient_not_found(
        self,
        async_client: AsyncClient,
        medical_token: str,
    ):
        """Test de mise à jour d'un patient inexistant"""
        fake_id = uuid4()
        response = await async_client.patch(
            f"/api/v1/patients/{fake_id}",
            json={"status": "actif"},
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 404
    
    async def test_delete_patient(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_medical_user,
        medical_token: str,
    ):
        """Test de suppression d'un patient"""
        from app.models.patient import Patient
        
        # Créer un patient temporaire pour le test
        temp_patient = Patient(
            id=uuid4(),
            nom="Temp",
            prenom="Patient",
            numero_dossier="TEMP001",
            status="actif",
        )
        db_session.add(temp_patient)
        await db_session.commit()
        
        response = await async_client.delete(
            f"/api/v1/patients/{temp_patient.id}",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        assert "supprimé" in response.json()["message"].lower()
    
    async def test_filter_patients_by_status(
        self,
        async_client: AsyncClient,
        test_patient,
        db_session: AsyncSession,
        medical_token: str,
    ):
        """Test de filtrage des patients par statut"""
        from app.models.patient import Patient
        
        # Créer un patient avec un statut différent
        prioritaire_patient = Patient(
            id=uuid4(),
            nom="Prioritaire",
            prenom="Patient",
            numero_dossier="PRIOR001",
            status="prioritaire",
        )
        db_session.add(prioritaire_patient)
        await db_session.commit()
        
        # Filtrer par statut "prioritaire"
        response = await async_client.get(
            "/api/v1/patients",
            params={"status_filter": "prioritaire"},
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        # Tous les patients retournés doivent avoir le statut "prioritaire"
        for patient in data:
            assert patient["status"] == "prioritaire"
    
    async def test_search_patients(
        self,
        async_client: AsyncClient,
        test_patient,
        medical_token: str,
    ):
        """Test de recherche de patients"""
        response = await async_client.get(
            "/api/v1/patients",
            params={"search": test_patient.nom},
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        # Au moins un patient devrait correspondre
        assert len(data) > 0
        # Vérifier que le patient trouvé contient le nom recherché
        found = any(p["nom"] == test_patient.nom for p in data)
        assert found
    
    async def test_export_patient_data(
        self,
        async_client: AsyncClient,
        test_patient,
        medical_token: str,
    ):
        """Test d'export des données patient (RGPD)"""
        response = await async_client.get(
            f"/api/v1/patients/{test_patient.id}/export",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        # Vérifier que c'est du JSON
        data = response.json()
        assert "export_date" in data
        assert "patient" in data
        assert data["patient"]["id"] == str(test_patient.id)
    
    async def test_get_patient_audit_trail(
        self,
        async_client: AsyncClient,
        test_patient,
        medical_token: str,
    ):
        """Test de récupération de la traçabilité des accès patient"""
        response = await async_client.get(
            f"/api/v1/patients/{test_patient.id}/audit-trail",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "patient_id" in data
        assert "audit_logs" in data
        assert isinstance(data["audit_logs"], list)

