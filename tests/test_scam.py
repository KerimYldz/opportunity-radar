from opportunity_radar import scam


def test_clean_post_low_risk_with_disclaimer():
    r = scam.assess("MOCK need help with a spreadsheet", "MOCK: I need my Excel budget sheet cleaned up, will pay $40 via PayPal.")
    assert r.score <= 25
    assert "does not verify" in r.explanation


def test_single_weak_signal_stays_low():
    r = scam.assess("MOCK spreadsheet help", "MOCK: Need a quick Excel fix. Message me on WhatsApp if you can help with the formulas.")
    assert r.score <= 15
    assert r.band == "Low apparent risk"


def test_fake_check_scheme_high_risk():
    r = scam.assess("MOCK easy data entry assistant",
                    "MOCK: I will send you a check, deposit the check and buy the equipment, we reimburse you. Text me on WhatsApp.")
    assert r.score >= 51
    codes = {s.code for s in r.signals}
    assert "fake_check" in codes
    assert all(s.evidence for s in r.signals)


def test_gift_cards_and_bank_details():
    r = scam.assess("MOCK task", "MOCK: Pay with gift cards. Also send your routing number so we can pay you.")
    assert r.score >= 51


def test_too_high_pay_for_trivial_work():
    r = scam.assess("MOCK easy 5 minute task", "MOCK: Simple copy paste job, $1500 per task, no experience needed.")
    assert any(s.code == "pay_too_high_for_trivial" for s in r.signals)


def test_short_text_marked_uncertain():
    assert scam.assess("MOCK help", "MOCK: dm me").uncertain


def test_bands():
    assert scam.band(0) == "Low apparent risk"
    assert scam.band(40) == "Some concerns"
    assert scam.band(60) == "High concern"
    assert scam.band(90) == "Very high concern"
