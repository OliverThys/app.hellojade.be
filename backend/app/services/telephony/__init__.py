"""
Module de téléphonie HelloJADE — Asterisk ARI + OVH SIP Trunk.

Architecture :
- Provider : Asterisk (ARI - Asterisk REST Interface)
- SIP Trunk : OVH
- TTS : Azure Cognitive Services Neural (fr-BE-CharlineNeural), fichier WAV joué par Asterisk
- STT : Azure Cognitive Services Speech SDK
- LLM : Mistral API (mistral-small-latest)
"""
