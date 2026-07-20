"""P5 data-integrity tests: derivations, the closed benign window, sources."""
from deckengine.llm.facts import FactTable, verify_spec_numbers

CSV = """State,Farmers,Income
UP,1030000,1216
Bihar,390000,1453
Odisha,760000,1209
"""


def test_derivations():
    t = FactTable()
    t.derive_pct_delta("d1", 1216, 1183, "UP income vs state avg", "src")
    t.derive_share("s1", 30, 120, "segment share")
    t.derive_multiple("m1", 150, 75, "Hybrid vs TELA")
    t.derive_cagr("c1", 100, 200, 5, "5y doubling")
    t.derive_rank("r1", "Bihar", {"UP": 10, "Bihar": 30, "Odisha": 20}, "rank")
    assert t.facts["d1"].display == "+2.8%"
    assert t.facts["s1"].display == "25%"
    assert t.facts["m1"].display == "2.0x"
    assert t.facts["c1"].display == "14.9%"
    assert t.facts["r1"].display == "#1"
    assert t.facts["d1"].source == "src"


def test_csv_ingestion_has_sources_and_shares():
    t = FactTable.from_csv(CSV, source_label="impact.csv")
    assert "impact.csv" in t.facts["farmers_sum"].source
    # per-row share derived: UP = 1.03M / 2.18M ~ 47%
    assert t.facts["row0_farmers_share"].display == "47%"
    assert "UP" in t.facts["row0_farmers_share"].description


def test_benign_window_closed_for_shares():
    """The review's loophole: '28% share' must NOT pass as benign."""
    t = FactTable.from_csv(CSV)
    suspects = verify_spec_numbers("Ola holds a 28% share of the market", t)
    assert "28" in suspects
    # ...even without the % sign, given risky context words
    suspects2 = verify_spec_numbers("market share of 28 points", t)
    assert "28" in suspects2


def test_small_counts_and_years_still_benign():
    t = FactTable.from_csv(CSV)
    assert verify_spec_numbers(
        "Five moves across 3 cities over 12 months from 2026", t) == []


def test_whitelisted_numbers_pass():
    t = FactTable.from_csv(CSV)
    assert verify_spec_numbers("Bihar households earned 1,453 on average", t) == []


def test_used_facts_and_appendix():
    from deckengine.llm.spec_generator import sources_appendix
    from deckengine.schema.slide_types import BulletContentSpec
    t = FactTable.from_csv(CSV, source_label="impact.csv")
    slide = BulletContentSpec(
        title="Bihar leads on income at 1,453 per household",
        bullets=[{"text": "Average income reached **1,453** in Bihar."}])
    appendix = sources_appendix(t, [slide])
    assert appendix is not None
    rows = appendix.table.groups[0].rows
    assert any("1,453" in r[1] for r in rows)
    assert any("impact.csv" in r[2] for r in rows)
