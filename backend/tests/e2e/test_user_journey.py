"""
Tests end-to-end pour les parcours utilisateur complets
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta


@pytest.mark.e2e
@pytest.mark.slow
class TestUserJourney:
    """Tests E2E pour les parcours utilisateur"""
    
    @pytest.mark.asyncio
    async def test_complete_user_journey_medical_staff(
        self,
        async_client,
        test_medical_user,
        medical_token: str,
        db_session,
        mocker,
    ):
        """
        Parcours complet d'un membre du personnel médical :
        1. Connexion
        2. Création d'un patient
        3. Initiation d'un appel
        4. Consultation des appels
        5. Export de données patient (RGPD)
        """
        # 1. Connexion (déjà fait via le token, mais on peut vérifier)
        me_response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert me_response.status_code == 200
        user_data = me_response.json()
        assert user_data["email"] == test_medical_user.email
        
        # 2. Création d'un patient
        from app.models.patient import Patient
        
        new_patient_data = {
            "nom": "Test",
            "prenom": "Journey",
            "email": "test.journey@example.com",
            "telephone": "+32470199999",
            "numero_dossier": f"JOURNEY{uuid4().hex[:4]}",
            "date_naissance": (datetime.now() - timedelta(days=365*55)).isoformat(),
            "date_sortie": datetime.now().isoformat(),
            "service_hospitalisation": "Général",
            "diagnostic_principal": "Suivi post-opératoire",
            "status": "actif",
            "consent_given": True,
            "risk_score": 5.0,
        }
        
        create_patient_response = await async_client.post(
            "/api/v1/patients",
            json=new_patient_data,
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert create_patient_response.status_code == 200
        patient_data = create_patient_response.json()
        patient_id = patient_data["id"]
        
        # 3. Initiation d'un appel (mocké)
        mock_asterisk = mocker.patch("app.services.telephony.asterisk_client.asterisk_client")
        mock_asterisk.originate_call.return_value = {
            "success": True,
            "call_id": str(uuid4()),
        }
        
        initiate_response = await async_client.post(
            f"/api/v1/calls/initiate/{patient_id}",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert initiate_response.status_code in [200, 202]
        call_data = initiate_response.json()
        call_id = call_data.get("id") or call_data.get("call_id")
        
        # 4. Consultation des appels
        calls_response = await async_client.get(
            "/api/v1/calls",
            params={"patient_id": patient_id},
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert calls_response.status_code == 200
        calls_list = calls_response.json()
        assert isinstance(calls_list, list)
        # Vérifier que l'appel créé est dans la liste
        call_ids = [call["id"] for call in calls_list]
        assert call_id in call_ids or str(call_id) in call_ids
        
        # 5. Export de données patient (RGPD)
        export_response = await async_client.get(
            f"/api/v1/patients/{patient_id}/export",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert export_response.status_code == 200
        export_data = export_response.json()
        assert "patient" in export_data
        assert export_data["patient"]["id"] == patient_id
        assert "calls" in export_data
        assert "audit_trail" in export_data
    
    @pytest.mark.asyncio
    async def test_admin_user_journey(
        self,
        async_client,
        test_admin_user,
        admin_token: str,
        mocker,
    ):
        """
        Parcours complet d'un administrateur :
        1. Connexion
        2. Consultation des logs d'audit
        3. Gestion des utilisateurs
        4. Export des logs d'audit
        """
        # 1. Connexion
        me_response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        assert me_response.status_code == 200
        user_data = me_response.json()
        assert user_data["role"] == "admin"
        
        # 2. Consultation des logs d'audit
        audit_logs_response = await async_client.get(
            "/api/v1/admin/audit-logs",
            params={"limit": 10},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        assert audit_logs_response.status_code == 200
        logs_data = audit_logs_response.json()
        assert "items" in logs_data or isinstance(logs_data, list)
        
        # 3. Gestion des utilisateurs - Lister les utilisateurs
        users_response = await async_client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        assert users_response.status_code == 200
        users_list = users_response.json()
        assert isinstance(users_list, list)
        
        # 4. Export des logs d'audit
        export_logs_response = await async_client.get(
            "/api/v1/admin/audit-logs/export",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        assert export_logs_response.status_code == 200
        # Vérifier que c'est du JSON
        export_logs_data = export_logs_response.json()
        assert isinstance(export_logs_data, list)
    
    @pytest.mark.asyncio
    async def test_gdpr_compliance_journey(
        self,
        async_client,
        test_admin_user,
        test_patient,
        admin_token: str,
        db_session,
    ):
        """
        Parcours de conformité RGPD :
        1. Consultation de la traçabilité
        2. Export des données patient
        3. Anonymisation des données patient
        """
        # 1. Consultation de la traçabilité
        audit_trail_response = await async_client.get(
            f"/api/v1/patients/{test_patient.id}/audit-trail",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        assert audit_trail_response.status_code == 200
        trail_data = audit_trail_response.json()
        assert "audit_logs" in trail_data
        assert "patient_id" in trail_data
        
        # 2. Export des données patient
        export_response = await async_client.get(
            f"/api/v1/patients/{test_patient.id}/export",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        assert export_response.status_code == 200
        export_data = export_response.json()
        assert export_data["patient"]["id"] == str(test_patient.id)
        
        # 3. Anonymisation des données patient
        delete_response = await async_client.delete(
            f"/api/v1/patients/{test_patient.id}/gdpr-delete",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        assert delete_response.status_code == 200
        delete_data = delete_response.json()
        assert delete_data["status"] == "success"
        assert "anonymization_applied" in delete_data
        
        # Vérifier que le patient est anonymisé
        get_patient_response = await async_client.get(
            f"/api/v1/patients/{test_patient.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        
        if get_patient_response.status_code == 200:
            patient_data = get_patient_response.json()
            # Les données personnelles doivent être anonymisées
            assert patient_data["nom"] == "ANONYMIZED" or patient_data["nom"] != test_patient.nom

