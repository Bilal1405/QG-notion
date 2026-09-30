from qg_sync.matching import extract_codes, normalize


def test_normalize_strips_accents_and_case():
    assert normalize("  Aé211 - Aéronautique  1 ") == "ae211 - aeronautique 1"


def test_extract_codes_handles_separators():
    assert extract_codes("2526_MA211_S1") == ["ma211"]
    assert extract_codes("Phs213 - Electromagnétisme 1") == ["phs213"]
    assert extract_codes("IPSA2026 Aero2") == []


def test_match_by_code(courses):
    assert courses.match("Ma211 - Analyse - calcul différentiel").page_id == "c-ma211"
    assert courses.match("[AE211] Aéronautique générale").page_id == "c-ae211"


def test_match_by_manual_key_then_name(courses):
    assert courses.match("Cours sans code", moodle_id=4242).page_id == "c-ae211"
    assert courses.match("aero-gen").page_id == "c-ae211"
    assert courses.match("Electromagnétisme 1").page_id == "c-phs213"


def test_no_match(courses):
    assert courses.match("Vie étudiante", "BDE") is None
