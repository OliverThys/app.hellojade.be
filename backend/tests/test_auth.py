"""
Tests unitaires pour l'authentification
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
@pytest.mark.unit
class TestAuth:
    """Tests pour les endpoints d'authentification"""
    
    async def test_login_success(
        self,
        async_client: AsyncClient,
        test_medical_user,
    ):
        """Test de connexion réussie"""
        response = await async_client.post(
            "/api/v1/auth/login",
            data={
                "username": test_medical_user.email,
                "password": "testpassword123",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
    
    async def test_login_invalid_credentials(
        self,
        async_client: AsyncClient,
        test_medical_user,
    ):
        """Test de connexion avec mauvais identifiants"""
        response = await async_client.post(
            "/api/v1/auth/login",
            data={
                "username": test_medical_user.email,
                "password": "wrongpassword",
            },
        )
        
        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()
    
    async def test_login_inactive_user(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Test de connexion avec utilisateur désactivé"""
        from app.core.security import get_password_hash
        from app.models.user import User
        from uuid import uuid4
        
        inactive_user = User(
            id=uuid4(),
            email="inactive@test.com",
            username="inactive",
            full_name="Inactive User",
            hashed_password=get_password_hash("testpassword123"),
            role="medical_staff",
            is_active=False,
        )
        db_session.add(inactive_user)
        await db_session.commit()
        
        response = await async_client.post(
            "/api/v1/auth/login",
            data={
                "username": inactive_user.email,
                "password": "testpassword123",
            },
        )
        
        assert response.status_code == 403
        assert "désactivé" in response.json()["detail"].lower()
    
    async def test_get_current_user(
        self,
        async_client: AsyncClient,
        test_medical_user,
        medical_token: str,
    ):
        """Test de récupération des informations de l'utilisateur connecté"""
        response = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_medical_user.email
        assert data["username"] == test_medical_user.username
    
    async def test_get_current_user_unauthorized(
        self,
        async_client: AsyncClient,
    ):
        """Test de récupération sans token"""
        response = await async_client.get("/api/v1/auth/me")
        
        assert response.status_code == 401
    
    async def test_refresh_token(
        self,
        async_client: AsyncClient,
        test_medical_user,
    ):
        """Test de rafraîchissement du token"""
        # D'abord se connecter pour obtenir un refresh token
        login_response = await async_client.post(
            "/api/v1/auth/login",
            data={
                "username": test_medical_user.email,
                "password": "testpassword123",
            },
        )
        
        refresh_token = login_response.json()["refresh_token"]
        
        # Rafraîchir le token
        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
    
    async def test_refresh_token_invalid(
        self,
        async_client: AsyncClient,
    ):
        """Test de rafraîchissement avec token invalide"""
        response = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid_token"},
        )
        
        assert response.status_code == 401
    
    async def test_logout(
        self,
        async_client: AsyncClient,
        medical_token: str,
    ):
        """Test de déconnexion"""
        response = await async_client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        assert "réussie" in response.json()["message"].lower()
    
    async def test_register(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Test d'enregistrement d'un nouvel utilisateur"""
        from uuid import uuid4
        
        new_user_data = {
            "email": f"newuser_{uuid4()}@test.com",
            "username": f"newuser_{uuid4().hex[:8]}",
            "full_name": "New User",
            "password": "testpassword123",
            "role": "caregiver",
            "is_active": True,
        }
        
        response = await async_client.post(
            "/api/v1/auth/register",
            json=new_user_data,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == new_user_data["email"]
        assert data["username"] == new_user_data["username"]
        # Le mot de passe ne doit pas être dans la réponse
        assert "password" not in data
        assert "hashed_password" not in data
    
    async def test_register_duplicate_email(
        self,
        async_client: AsyncClient,
        test_medical_user,
    ):
        """Test d'enregistrement avec email déjà utilisé"""
        from uuid import uuid4
        
        new_user_data = {
            "email": test_medical_user.email,  # Email déjà utilisé
            "username": f"newuser_{uuid4().hex[:8]}",
            "full_name": "New User",
            "password": "testpassword123",
            "role": "caregiver",
        }
        
        response = await async_client.post(
            "/api/v1/auth/register",
            json=new_user_data,
        )
        
        assert response.status_code == 400
        assert "existe déjà" in response.json()["detail"].lower()
    
    async def test_change_password(
        self,
        async_client: AsyncClient,
        test_medical_user,
        medical_token: str,
    ):
        """Test de changement de mot de passe"""
        response = await async_client.post(
            "/api/v1/auth/change-password",
            json={
                "old_password": "testpassword123",
                "new_password": "newpassword456",
            },
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 200
        assert "modifié" in response.json()["message"].lower()
        
        # Vérifier que le nouveau mot de passe fonctionne
        login_response = await async_client.post(
            "/api/v1/auth/login",
            data={
                "username": test_medical_user.email,
                "password": "newpassword456",
            },
        )
        
        assert login_response.status_code == 200
    
    async def test_change_password_wrong_old_password(
        self,
        async_client: AsyncClient,
        medical_token: str,
    ):
        """Test de changement de mot de passe avec ancien mot de passe incorrect"""
        response = await async_client.post(
            "/api/v1/auth/change-password",
            json={
                "old_password": "wrongpassword",
                "new_password": "newpassword456",
            },
            headers={"Authorization": f"Bearer {medical_token}"},
        )
        
        assert response.status_code == 400
        assert "incorrect" in response.json()["detail"].lower()

