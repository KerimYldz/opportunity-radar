from opportunity_radar import dedup


def test_reddit_urls_canonicalize_to_post_id():
    a = dedup.canonical_url("https://old.reddit.com/r/forhire/comments/AbC123/some_title/?utm_source=x")
    b = dedup.canonical_url("https://www.reddit.com/r/forhire/comments/abc123/")
    c = dedup.canonical_url("https://redd.it/abc123")
    assert a == b == c == "https://www.reddit.com/comments/abc123"


def test_generic_url_canonicalization():
    assert dedup.canonical_url("https://Example.com/post/1/?ref=a#x") == "https://example.com/post/1"


def test_fingerprint_ignores_case_and_punctuation():
    assert dedup.fingerprint("MOCK Need Excel help!", "Fix my sheet.") == dedup.fingerprint("mock need excel help", "fix my sheet")


def test_near_duplicate_similarity():
    a = dedup.shingles("MOCK need someone to clean my excel customer list remove duplicates and fix formatting pay 50")
    b = dedup.shingles("MOCK need someone to clean my excel customer list remove duplicates and fix formatting pay 60")
    assert dedup.jaccard(a, b) >= 0.8
    c = dedup.shingles("MOCK build a wordpress landing page for my bakery")
    assert dedup.jaccard(a, c) < 0.2
