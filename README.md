<p align="center">
  <img src="frontend/assets/hellojade_logo.png" alt="HelloJADE Logo" width="180"/>
</p>

<h1 align="center">HelloJADE</h1>

<p align="center">
  <strong>Assistant vocal IA pour le suivi post-hospitalisation</strong><br/>
  <em>Démo non affiliée Épiçura — app.hellojadeapp.be</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/Azure_AI-Speech-0078D4?style=for-the-badge&logo=microsoftazure&logoColor=white"/>
  <img src="https://img.shields.io/badge/Mistral_AI-LLM-FF7000?style=for-the-badge&logo=mistral&logoColor=white"/>
  <img src="https://img.shields.io/badge/Asterisk-20-F47920?style=for-the-badge&logo=asterisk&logoColor=white"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/Redis-7-DC382D?style=for-the-badge&logo=redis&logoColor=white"/>
  <img src="https://img.shields.io/badge/Keycloak-24-4D4D4D?style=for-the-badge&logo=keycloak&logoColor=white"/>
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white"/>
  <img src="https://img.shields.io/badge/Cloudflare-Tunnel-F38020?style=for-the-badge&logo=cloudflare&logoColor=white"/>
</p>

---

## 📋 Table des matières

- [Description](#-description)
- [Fonctionnalités](#-fonctionnalités)
- [Architecture](#-architecture)
- [Stack technique](#-stack-technique)
- [Déploiement](#-déploiement)
- [Variables d'environnement](#-variables-denvironnement)
- [API](#-api)
- [Téléphonie](#-téléphonie-asterisk)
- [Monitoring](#-monitoring)
- [Sécurité & RGPD](#-sécurité--rgpd)

---

## 🏥 Description

HelloJADE est un assistant vocal IA conçu pour le **suivi post-hospitalisation** des patients. Il contacte automatiquement les patients par téléphone après leur sortie d'hôpital, conduit un questionnaire médical adaptatif en langage naturel, et transmet les résultats aux équipes soignantes sous forme de rapports structurés.

Le système est conçu pour s'intégrer dans l'écosystème hospitalier via les standards **HL7 / FHIR** et les protocoles **SAML2 / SSO** des établissements de santé.

---

## ✨ Fonctionnalités

| Fonctionnalité | Description |
|---|---|
| 📞 **Appels sortants automatisés** | Campagnes d'appels planifiées via trunk SIP OVH |
| 🎙️ **Reconnaissance vocale (STT)** | Azure Cognitive Services — `fr-BE-CharlineNeural` |
| 🔊 **Synthèse vocale (TTS)** | Azure Neural TTS, cache WAV local pour latence minimale |
| 🧠 **IA conversationnelle** | Mistral API (`mistral-small-latest`) pour l'analyse médicale |
| 📊 **Questionnaires adaptatifs** | Questions de suivi dynamiques selon les réponses du patient |
| 📄 **Rapports PDF** | Génération automatique post-appel avec synthèse IA |
| 🏥 **Intégration HL7** | Export ORU vers Mirth Connect via SFTP |
| 🔐 **SSO SAML2** | Authentification via Keycloak 24 (realm Épiçura) |
| 📈 **Analytics & Dashboard** | Métriques temps réel, taux de complétion, AMD |
| 🔁 **Retry intelligent** | Rappel automatique si patient non joignable |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Internet / PSTN                              │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │   Cloudflare Tunnel     │  app.hellojadeapp.be
          └────────────┬────────────┘
                       │ HTTPS
          ┌────────────▼────────────┐
          │   Nginx (port 8080)     │  Reverse proxy + static files
          └─────┬──────────┬────────┘
                │          │
    ┌───────────▼──┐  ┌────▼───────────────┐
    │   Frontend   │  │  FastAPI Backend   │  hellojadeapp-backend
    │  (HTML/JS)   │  │  + Celery Workers  │  hellojadeapp-celery
    └──────────────┘  └────┬───────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼──────┐  ┌────────▼──────┐  ┌───────▼────────┐
│ PostgreSQL16 │  │    Redis 7    │  │  Keycloak 24   │
│  (données)   │  │  (cache/queue)│  │  (SSO SAML2)   │
└──────────────┘  └───────────────┘  └────────────────┘

          ┌────────────────────────────────┐
          │   Asterisk 20 (NATIF)          │  /etc/asterisk/
          │   • Trunk SIP OVH             │
          │   • AMD (Answering Machine)   │
          │   • ARI WebSocket :8088       │
          │   • MixMonitor (enregistrement│
          └──────────────┬─────────────────┘
                         │ ARI WebSocket
          ┌──────────────▼─────────────────┐
          │   asterisk_ari_service.py       │  Orchestre les appels
          └──────────────┬─────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼──────┐ ┌───────▼──────┐ ┌──────▼───────┐
│  Azure STT   │ │  Azure TTS   │ │  Mistral API │
│  (écoute)    │ │  (parole)    │ │  (analyse)   │
└──────────────┘ └──────────────┘ └──────────────┘
```

### Flux d'un appel

```
Celery Beat → Tâche planifiée → Asterisk originate → Patient décroche
    → AMD (humain détecté) → ARI WebSocket → Backend
    → TTS "Bonjour, je suis JADE..." → Azure Speech → Fichier WAV
    → Asterisk joue WAV → Patient répond → Azure STT → Texte
    → Mistral analyse → Question suivante → ... → Fin questionnaire
    → Rapport PDF généré → HL7 ORU exporté via SFTP → Mirth
```

---

## 🛠️ Stack technique

<table>
  <thead>
    <tr>
      <th>Couche</th>
      <th>Technologie</th>
      <th>Rôle</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><img src="https://img.shields.io/badge/-Backend-009688?style=flat-square&logo=fastapi&logoColor=white"/></td>
      <td>FastAPI 0.115 + Python 3.12</td>
      <td>API REST async, WebSocket ARI</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-Tasks-37814A?style=flat-square&logo=celery&logoColor=white"/></td>
      <td>Celery 5.4 + Redis</td>
      <td>Campagnes d'appels, retry, beat scheduler</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-STT-0078D4?style=flat-square&logo=microsoftazure&logoColor=white"/></td>
      <td>Azure Speech SDK 1.41</td>
      <td>Reconnaissance vocale fr-BE</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-TTS-0078D4?style=flat-square&logo=microsoftazure&logoColor=white"/></td>
      <td>Azure Neural TTS</td>
      <td>Synthèse fr-BE-CharlineNeural + cache WAV</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-LLM-FF7000?style=flat-square&logo=mistral&logoColor=white"/></td>
      <td>Mistral API (mistral-small-latest)</td>
      <td>Analyse médicale, NLU, génération rapports</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-Téléphonie-F47920?style=flat-square&logo=asterisk&logoColor=white"/></td>
      <td>Asterisk 20 + OVH SIP Trunk</td>
      <td>PSTN, AMD, enregistrement, ARI</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-Auth-4D4D4D?style=flat-square&logo=keycloak&logoColor=white"/></td>
      <td>Keycloak 24 (SAML2)</td>
      <td>SSO, realm Épiçura, gestion rôles</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-DB-4169E1?style=flat-square&logo=postgresql&logoColor=white"/></td>
      <td>PostgreSQL 16 + Alembic</td>
      <td>Patients, appels, questionnaires, rapports</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-Cache-DC382D?style=flat-square&logo=redis&logoColor=white"/></td>
      <td>Redis 7</td>
      <td>Cache sessions, broker Celery</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-Proxy-009639?style=flat-square&logo=nginx&logoColor=white"/></td>
      <td>Nginx</td>
      <td>Reverse proxy, TLS termination</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-Tunnel-F38020?style=flat-square&logo=cloudflare&logoColor=white"/></td>
      <td>Cloudflare Tunnel</td>
      <td>Exposition HTTPS sans port ouvert</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-HL7-005EB8?style=flat-square"/></td>
      <td>HL7 ORU + Mirth Connect</td>
      <td>Interopérabilité hospitalière via SFTP</td>
    </tr>
    <tr>
      <td><img src="https://img.shields.io/badge/-Monitoring-E6522C?style=flat-square&logo=prometheus&logoColor=white"/></td>
      <td>Prometheus + Flower</td>
      <td>Métriques backend + supervision Celery</td>
    </tr>
  </tbody>
</table>

---

## 🚀 Déploiement

### Prérequis

- Docker + Docker Compose
- Asterisk 20 (natif — **ne pas dockeriser**)
- Ubuntu 22.04+
- Compte OVH SIP Trunk
- Compte Azure (Speech Services)
- Compte Mistral API

### 1. Cloner le repo

```bash
git clone https://github.com/OliverThys/app.hellojade.be.git
cd app.hellojade.be
```

### 2. Configurer l'environnement

```bash
cp .env.example .env
# Éditer .env avec vos clés API et paramètres
```

### 3. Lancer la stack Docker

```bash
docker compose -f docker-compose.ovh.yml up -d
```

### 4. Configurer Asterisk

```bash
# Copier les fichiers de config dans /etc/asterisk/
# Vérifier le trunk SIP
asterisk -rx 'pjsip show registrations'
```

### 5. Vérifier le symlink TTS

```bash
# Critique : Asterisk lit les WAV générés via ce symlink
ls -la /var/lib/asterisk/sounds/custom
# Doit pointer vers /root/hellojade/temp/tts
```

### 6. Migrations base de données

```bash
docker exec hellojadeapp-backend alembic upgrade head
```

---

### Mise à jour du backend (sans rebuild)

```bash
docker cp /root/hellojade/backend/app/. hellojadeapp-backend:/app/app/
docker restart hellojadeapp-backend hellojadeapp-celery hellojadeapp-celery-beat
```

> ⚠️ Après un `--force-recreate`, re-injecter `saml_service.py` (le flag `validate_schema=False` est perdu).

---

## ⚙️ Variables d'environnement

Copier `.env.example` et renseigner les valeurs :

```env
# Base de données
DATABASE_URL=postgresql+asyncpg://hellojade:password@postgres:5432/hellojade_db

# Redis
REDIS_URL=redis://redis:6379/0

# Azure Cognitive Services
AZURE_SPEECH_KEY=your_key_here
AZURE_SPEECH_REGION=westeurope

# Mistral API
MISTRAL_API_KEY=your_key_here

# Asterisk ARI
ASTERISK_ARI_URL=http://localhost:8088
ASTERISK_ARI_USER=hellojadeapp
ASTERISK_ARI_PASSWORD=hellojadeari2024

# Keycloak / SAML2
KEYCLOAK_SERVER_URL=http://keycloak:8080
SAML_IDP_METADATA_URL=...

# OVH SIP
OVH_SIP_USER=...
OVH_SIP_PASSWORD=...
```

---

## 📡 API

La documentation interactive est disponible sur `/api/docs` (Swagger UI).

| Endpoint | Description |
|---|---|
| `GET /api/v1/patients` | Liste des patients |
| `POST /api/v1/calls` | Déclencher un appel |
| `GET /api/v1/calls/{id}` | Détail d'un appel |
| `GET /api/v1/reports/{id}` | Rapport PDF d'un appel |
| `GET /api/v1/dashboard` | Métriques et statistiques |
| `GET /api/v1/analytics` | Analytics avancées |
| `POST /api/v1/auth/saml` | SSO SAML2 Keycloak |
| `WS /api/v1/ws` | WebSocket temps réel |
| `GET /metrics` | Métriques Prometheus |

---

## 📞 Téléphonie Asterisk

Asterisk tourne en **natif** (hors Docker) pour des raisons de compatibilité RTP/NAT.

### Fichiers clés

| Fichier | Rôle |
|---|---|
| `/etc/asterisk/pjsip.conf` | Trunk OVH SIP (`external_media_address = 51.68.224.55`) |
| `/etc/asterisk/extensions.conf` | Dialplan : AMD → MixMonitor → Stasis |
| `/etc/asterisk/ari.conf` | ARI user : `hellojadeapp` / `hellojadeari2024` |
| `/etc/asterisk/http.conf` | ARI HTTP sur `0.0.0.0:8088` |

### Commandes utiles

```bash
# État des enregistrements SIP
asterisk -rx 'pjsip show registrations'

# Canaux actifs
asterisk -rx 'core show channels'

# Console verbose (debug live)
asterisk -rvvv

# Règles RTP (persistées via iptables)
iptables -L -n | grep -E '5060|16[0-9]{3}'
```

### Points critiques

- **iptables** : règles RTP (UDP 16000–16999) et SIP (5060) persistées via `iptables-save`
- **`HELLOJADE_APP`** dans `extensions.conf` : toujours via variable, jamais hardcodé
- **Symlink** : `/var/lib/asterisk/sounds/custom` → `/root/hellojade/temp/tts`

---

## 📊 Monitoring

| Service | URL | Description |
|---|---|---|
| **Swagger UI** | `/api/docs` | Documentation API interactive |
| **Flower** | `http://localhost:5555` | Supervision des workers Celery |
| **Prometheus** | `/metrics` | Métriques FastAPI |
| **Keycloak Admin** | `/auth/admin` | Gestion SSO |

---

## 🔐 Sécurité & RGPD

- **Authentification** : SSO SAML2 via Keycloak 24 — aucune gestion de mot de passe en local
- **Chiffrement** : TLS end-to-end via Cloudflare Tunnel (pas de port 443 ouvert)
- **Données patients** : stockées exclusivement sur le VPS OVH (EU), jamais envoyées à des tiers sauf Azure/Mistral (DPA signés)
- **Enregistrements** : fichiers WAV chiffrés au repos, supprimés selon politique de rétention RGPD
- **Logs** : anonymisés (pas de numéro de téléphone en clair dans les logs)
- **Secrets** : gérés via `.env` (jamais commités), aucun secret en dur dans le code

---

## 📁 Structure du projet

```
hellojade/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/    # Routes FastAPI
│   │   ├── core/                # Config, sécurité, logging
│   │   ├── models/              # Modèles SQLAlchemy
│   │   ├── services/
│   │   │   ├── ai/              # Azure STT/TTS, Mistral
│   │   │   └── telephony/       # Asterisk ARI, questionnaires
│   │   └── tasks/               # Tâches Celery
│   ├── alembic/                 # Migrations DB
│   └── Dockerfile
├── frontend/                    # Interface HTML/JS
├── keycloak/                    # Realm Keycloak (sans users)
├── nginx/                       # Config Nginx
├── docker-compose.ovh.yml       # Stack Docker principale
└── .env.example                 # Template variables d'environnement
```

---

<p align="center">
  Développé avec ❤️ par <strong>Oliver Thys</strong> — HelloJADE © 2024–2025
</p>
