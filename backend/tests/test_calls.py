"""
Tests unitaires pour la gestion des appels
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from datetime import datetime, timedelta


@pytest.mark.asyncio
@pytest.mark.unit
class TestCalls:
    """Tests pour les endpoints de gestion des appels"""
    
    async def test_get_calls(
        self,
        async_client: AsyncClient,
        test_call,
        medical_token: str,
    ):
        """Test de récupération de la liste des appels"""
        response = await async_client.get(
            "/api/v1/calls",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    async def test_get_call_by_id(
        self,
        async_client: AsyncClient,
        test_call,
        medical_token: str,
    ):
        """Test de récupération d'un appel par ID"""
        response = await async_client.get(
            f"/api/v1/calls/{test_call.id}",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_call.id)
        assert data["status"] == test_call.status
    
    async def test_get_call_not_found(
        self,
        async_client: AsyncClient,
        medical_token: str,
    ):
        """Test de récupération d'un appel inexistant"""
        fake_id = uuid4()
        response = await async_client.get(
            f"/api/v1/calls/{fake_id}",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 404
    
    async def test_initiate_call(
        self,
        async_client: AsyncClient,
        test_patient,
        test_medical_user,
        medical_token: str,
        mocker,
    ):
        """Test d'initiation d'un appel"""
        # Mocker le client Asterisk pour éviter de faire un vrai appel
        mock_asterisk = mocker.patch("app.services.telephony.asterisk_client.asterisk_client")
        mock_asterisk.originate_call.return_value = {"success": True, "call_id": str(uuid4())}
        
        response = await async_client.post(
            f"/api/v1/calls/initiate/{test_patient.id}",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        # Le statut peut être 200 (succès) ou 202 (en cours)
        assert response.status_code in [200, 202]
        data = response.json()
        assert "id" in data or "call_id" in data
    
    async def test_update_call_status(
        self,
        async_client: AsyncClient,
        test_call,
        medical_token: str,
    ):
        """Test de mise à jour du statut d'un appel"""
        update_data = {
            "status": "completed",
            "duration": 300,
        }
        
        response = await async_client.patch(
            f"/api/v1/calls/{test_call.id}",
            json=update_data,
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == update_data["status"]
        assert data["duration"] == update_data["duration"]
    
    async def test_update_call_status_unauthorized(
        self,
        async_client: AsyncClient,
        test_call,
    ):
        """Test de mise à jour sans authentification"""
        response = await async_client.patch(
            f"/api/v1/calls/{test_call.id}",
            json={"status": "completed"},
        )
        
        assert response.status_code == 401
    
    async def test_get_calls_by_patient(
        self,
        async_client: AsyncClient,
        test_call,
        test_patient,
        medical_token: str,
    ):
        """Test de récupération des appels d'un patient"""
        response = await async_client.get(
            "/api/v1/calls",
            params={"patient_id": str(test_patient.id)},
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Vérifier que tous les appels appartiennent au patient
        for call in data:
            assert call["patient_id"] == str(test_patient.id)
    
    async def test_filter_calls_by_status(
        self,
        async_client: AsyncClient,
        test_call,
        medical_token: str,
    ):
        """Test de filtrage des appels par statut"""
        response = await async_client.get(
            "/api/v1/calls",
            params={"status": "completed"},
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        # Tous les appels retournés doivent avoir le statut "completed"
        for call in data:
            assert call["status"] == "completed"
    
    async def test_transcribe_call(
        self,
        async_client: AsyncClient,
        test_call,
        admin_token: str,
        mocker,
    ):
        """Test de transcription d'un appel"""
        response = await async_client.post(
            f"/api/v1/calls/{test_call.id}/transcribe",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        # Peut être 200 (synchrone) ou 202 (asynchrone)
        assert response.status_code in [200, 202]
    
    async def test_analyze_call(
        self,
        async_client: AsyncClient,
        test_call,
        admin_token: str,
        mocker,
    ):
        """Test d'analyse d'un appel"""
        
        response = await async_client.post(
            f"/api/v1/calls/{test_call.id}/analyze",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        # Peut être 200 (synchrone) ou 202 (asynchrone)
        assert response.status_code in [200, 202]

