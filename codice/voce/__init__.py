"""Modulo Voce (Tappa 6): I/O audio sopra l'Orchestratore.

La logica pura (frasi, sanificazione, riempitivi, conferme) è testata in CI;
i wrapper audio (mic/casse/WebSocket verso Deepgram/ElevenLabs) hanno
dipendenze locali (vedi requirements-voce.txt) e si verificano in reale.
"""
