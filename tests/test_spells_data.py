import os

import spells_data as SD


def test_diagrams_exist():
    assert len(SD.SPELLS) >= 60
    for s in SD.SPELLS:
        for p in SD.diagram_paths(s):
            assert os.path.exists(p)


def test_effect_uses_custom_colour():
    eff = SD.spell_effect("lumos", (1, 2, 3))
    assert ("led", 0, 1, 2, 3, 300) in eff


def test_pretty_names():
    assert SD.pretty("expecto_patronum") == "Expecto Patronum"


def test_descriptions_refer_to_known_spells():
    assert set(SD.DESCRIPTIONS) <= set(SD.SPELLS) | {"lumos_maxima"}


def test_spell_key_normalises_names_from_the_wand():
    assert SD.spell_key("Protego") == "protego"
    assert SD.spell_key("Wingardium Leviosa") == "wingardium_leviosa"
    assert SD.spell_key("The_Stretching_Jinx") == "the_stretching_jinx"
    assert SD.spell_key("  Expecto-Patronum ") == "expecto_patronum"
    assert SD.spell_key("") == "" and SD.spell_key(None) == ""
    assert SD.spell_key("Protego") in SD.SPELLS
