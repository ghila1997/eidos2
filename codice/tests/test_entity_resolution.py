"""Trappola reale trovata nelle mail vere di Nastro Tecno (sessione
2026-07-23): 'Isagro' e 'ISAGRO S.p.A.' devono risolvere allo stesso
entity_key, altrimenti un impegno aperto su una forma e chiuso sull'altra
restano due entità diverse per sempre."""
from memoria.entity_resolution import slug_entity


def test_slug_entity_nome_semplice():
    assert slug_entity("Isagro") == "isagro"


def test_slug_entity_ignora_suffisso_spa_con_punti():
    assert slug_entity("ISAGRO S.p.A.") == "isagro"


def test_slug_entity_ignora_suffisso_srl():
    assert slug_entity("Nastro Tecno Srl") == "nastro_tecno"


def test_slug_entity_ignora_suffisso_srl_con_punti():
    assert slug_entity("Nastro Tecno S.r.l.") == "nastro_tecno"


def test_slug_entity_nomi_diversi_restano_diversi():
    assert slug_entity("Isagro") != slug_entity("Gowanco")
