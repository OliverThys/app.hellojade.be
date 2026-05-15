"""
Configuration et fixtures pour les tests pytest
"""
import asyncio
from typing import AsyncGenerator, Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.models.patient import Patient
from app.models.call import Call


# Base de données de test (SQLite en mémoire pour les tests)
# Note: Nécessite aiosqlite pour async SQLite
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Engine de test
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Session factory de test
TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Créer un event loop pour les tests asynchrones"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Créer une session de base de données de test"""
    # Créer les tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Créer une session
    async with TestSessionLocal() as session:
        yield session
    
    # Nettoyer après le test
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
def override_get_db(db_session: AsyncSession):
    """Override de la dépendance get_db pour utiliser la DB de test"""
    async def _get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client(override_get_db) -> TestClient:
    """Client de test FastAPI"""
    return TestClient(app)


@pytest.fixture
async def async_client(override_get_db) -> AsyncGenerator[AsyncClient, None]:
    """Client asynchrone de test FastAPI"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# ==================== FIXTURES UTILISATEURS ====================

@pytest.fixture
async def test_admin_user(db_session: AsyncSession) -> User:
    """Créer un utilisateur admin de test"""
    from app.core.security import get_password_hash
    
    user = User(
        id=uuid4(),
        email="admin@test.com",
        username="admin",
        full_name="Admin Test",
        hashed_password=get_password_hash("testpassword123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_medical_user(db_session: AsyncSession) -> User:
    """Créer un utilisateur médical de test"""
    from app.core.security import get_password_hash
    
    user = User(
        id=uuid4(),
        email="doctor@test.com",
        username="doctor",
        full_name="Doctor Test",
        hashed_password=get_password_hash("testpassword123"),
        role="medical_staff",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_caregiver_user(db_session: AsyncSession) -> User:
    """Créer un utilisateur soignant de test"""
    from app.core.security import get_password_hash
    
    user = User(
        id=uuid4(),
        email="caregiver@test.com",
        username="caregiver",
        full_name="Caregiver Test",
        hashed_password=get_password_hash("testpassword123"),
        role="caregiver",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def admin_token(test_admin_user: User) -> str:
    """Token JWT pour l'utilisateur admin"""
    return create_access_token(
        subject=test_admin_user.id,
        additional_claims={"role": test_admin_user.role, "email": test_admin_user.email},
    )


@pytest.fixture
def medical_token(test_medical_user: User) -> str:
    """Token JWT pour l'utilisateur médical"""
    return create_access_token(
        subject=test_medical_user.id,
        additional_claims={"role": test_medical_user.role, "email": test_medical_user.email},
    )


@pytest.fixture
def caregiver_token(test_caregiver_user: User) -> str:
    """Token JWT pour l'utilisateur soignant"""
    return create_access_token(
        subject=test_caregiver_user.id,
        additional_claims={"role": test_caregiver_user.role, "email": test_caregiver_user.email},
    )


# ==================== FIXTURES PATIENTS ====================

@pytest.fixture
async def test_patient(db_session: AsyncSession, test_admin_user: User) -> Patient:
    """Créer un patient de test"""
    from datetime import datetime, timedelta
    
    patient = Patient(
        id=uuid4(),
        nom="Dupont",
        prenom="Jean",
        email="jean.dupont@example.com",
        telephone="+32470123456",
        numero_dossier="P001",
        date_naissance=datetime.now() - timedelta(days=365*50),
        date_sortie=datetime.now() - timedelta(days=2),
        service_hospitalisation="Cardiologie",
        diagnostic_principal="Infarctus du myocarde",
        status="actif",
        consent_given=True,
        consent_date=datetime.now() - timedelta(days=1),
        risk_score=5.5,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)
    return patient


# ==================== FIXTURES APPELS ====================

@pytest.fixture
async def test_call(
    db_session: AsyncSession,
    test_patient: Patient,
    test_medical_user: User,
) -> Call:
    """Créer un appel de test"""
    from datetime import datetime, timedelta
    
    call = Call(
        id=uuid4(),
        patient_id=test_patient.id,
        created_by=test_medical_user.id,
        status="completed",
        callee_number=test_patient.telephone,
        duration=180,
        start_time=datetime.now() - timedelta(minutes=30),
        end_time=datetime.now() - timedelta(minutes=27),
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)
    return call

