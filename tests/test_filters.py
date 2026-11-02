from opportunity_radar import filters

from .conftest import mock_post


def test_clear_paid_excel_task_passes_with_high_suitability(settings):
    a = filters.analyze(mock_post(), settings, age_hours=2)
    assert a.passed
    assert a.intent == "request"
    assert "spreadsheet" in a.categories
    assert a.suitability >= 75
    assert a.advertised_budget and "$50" in a.advertised_budget
    assert a.remote == "remote"


def test_offer_is_rejected(settings):
    p = mock_post(title="[For Hire] MOCK Excel expert, I will build any spreadsheet",
                  body="MOCK: Hire me for Excel work. My rates start at $20/hr.")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.intent == "offer"
    assert not a.passed and a.reject_reason == "offering_services"


def test_full_time_job_is_rejected(settings):
    p = mock_post(title="[Hiring] MOCK Full-time data analyst (Excel)",
                  body="MOCK: Full-time role with salary and benefits package. Excel required.")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.reject_reason == "full_time_employment"


def test_irrelevant_category_rejected(settings):
    p = mock_post(title="[Task] MOCK need someone to walk my dog", body="MOCK: Need someone to walk my dog daily, will pay $20.")
    assert filters.analyze(p, settings, age_hours=1).reject_reason == "no_target_category"


def test_in_person_outside_area_rejected(settings):
    p = mock_post(title="[Task] MOCK need computer help", body="MOCK: Need computer help in person at my house in Phoenix, AZ. Will pay $40.")
    assert filters.analyze(p, settings, age_hours=1).reject_reason == "physical_presence_outside_area"


def test_in_person_in_area_allowed(settings):
    p = mock_post(title="[Task] MOCK need computer help", body="MOCK: Need computer help in person at my house in Cherry Hill. Will pay $40.")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.passed and a.remote == "local-ok"


def test_old_post_rejected(settings):
    assert filters.analyze(mock_post(), settings, age_hours=24 * 10).reject_reason == "too_old"


def test_free_help_subreddit_penalized(settings):
    p = mock_post(title="MOCK How do I fix my VLOOKUP formula?", body="MOCK: Can someone help me, my excel formula returns #N/A for every row of the sheet.", sub="r/excel")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.suitability < 75


def test_complex_project_penalized(settings):
    p = mock_post(title="[Hiring] MOCK need a mobile app like Uber with a website", body="MOCK: Looking for someone to build a full-stack mobile app and website, long-term project. Budget $300.")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.complexity == "high"
    assert a.suitability < 75


def test_budget_never_invented(settings):
    p = mock_post(body="MOCK: Need someone to convert 20 PDF invoices into one Excel sheet. Remote.")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.advertised_budget is None
    assert a.est_price_low is not None  # estimate is separate from advertised budget


def test_website_word_alone_is_not_a_category(settings):
    p = mock_post(title="MOCK Flying with a puppy", body="MOCK: The airline website says pets are allowed. Can someone help me understand the rules?", sub="r/travel")
    assert filters.analyze(p, settings, age_hours=1).reject_reason == "no_target_category"


def test_website_request_matches(settings):
    p = mock_post(title="MOCK need someone to build a simple website for my bakery", body="MOCK: Small bakery in Haddonfield, need a basic website with menu and hours. Budget around $150.", sub="r/southjersey")
    a = filters.analyze(p, settings, age_hours=1)
    assert "website" in a.categories and a.passed


def test_general_question_without_hire_intent_is_capped(settings):
    p = mock_post(title="MOCK can someone help me with my excel formula", body="MOCK: My SUMIF in this spreadsheet keeps returning zero for every row, what am I doing wrong here?", sub="r/Accounting")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.suitability <= 60


def test_local_neighbor_ask_with_hire_intent(settings):
    p = mock_post(title="MOCK Does anyone know someone who can organize my Excel customer database?", body="MOCK: Small business in Cherry Hill. Our customer list in Excel is a mess with duplicates. Does anyone know someone who could clean it up? Can be remote.", sub="r/southjersey")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.passed and a.suitability >= 75


def test_no_unpaid_trial_is_not_excluded(settings):
    p = mock_post(title="[TASK] MOCK basic IT support, remote", body="MOCK: Need help troubleshooting a software license issue on Windows. All work is paid, there are no unpaid trial assignments. $20.")
    a = filters.analyze(p, settings, age_hours=1)
    assert a.reject_reason is None and "computer_help" in a.categories


def test_incidental_keyword_does_not_match(settings):
    p = mock_post(title="[TASK] MOCK voiceover for a 3 minute YouTube video", body="MOCK: Record a voiceover. Then I will send you a screenshot of our channel dashboard to film. $20.")
    assert filters.analyze(p, settings, age_hours=1).reject_reason == "no_target_category"


def test_license_reverse_engineering_is_suspicious(settings):
    p = mock_post(title="[Hiring] MOCK Software License Troubleshooting",
                  body="MOCK: I need an expert in reverse engineering to inspect the licensing mechanism of a bot and restore access. $15/hr.",
                  sub="r/forhire")
    assert filters.analyze(p, settings, age_hours=1).reject_reason == "suspicious_request"


def test_lookup_and_macro_words_need_spreadsheet_context(settings):
    p1 = mock_post(title="MOCK Apple ID Lookup website", body="MOCK: is there a way to look up an Apple ID? If there's a paid method I'm willing to pay.", sub="r/iphone")
    p2 = mock_post(title="MOCK bearish on QQQ", body="MOCK: I need to watch the macro picture before Monday. Paid subscribers get more.", sub="r/stocks")
    assert filters.analyze(p1, settings, age_hours=1).reject_reason == "no_target_category"
    assert filters.analyze(p2, settings, age_hours=1).reject_reason == "no_target_category"
    p3 = mock_post(title="[Task] MOCK fix my VLOOKUP and write an Excel macro", body="MOCK: Need someone to fix a VLOOKUP and write a small VBA macro. $40.")
    assert filters.analyze(p3, settings, age_hours=1).passed


def test_activation_lock_bypass_rejected(settings):
    p = mock_post(title="[Task] MOCK remove activation lock from iPhone", body="MOCK: Need someone to bypass the activation lock on an iPhone, will pay $50.", sub="r/ActivationLockBypass")
    assert filters.analyze(p, settings, age_hours=1).reject_reason in {"blocked_community", "suspicious_request"}
