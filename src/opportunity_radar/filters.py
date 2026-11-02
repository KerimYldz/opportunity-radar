"""Stage 1: deterministic rule-based filtering and assessment.

Everything here is conservative inference from the post text. Budgets are only ever
copied verbatim from the post; price and time figures are labelled as estimates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import scam as scam_mod
from .models import Assessment, RawPost


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


# category -> (strong pattern, weak pattern, (price_low, price_high), base_hours)
@dataclass(frozen=True)
class Category:
    name: str
    strong: re.Pattern
    weak: re.Pattern | None
    price: tuple[int, int]
    hours: float


CATEGORIES = [
    Category("spreadsheet", _rx(r"\bexcel\b(?!\s+(in|at|as)\b)",r"\bspreadsheets?\b", r"\bxlsx?\b", r"\b[vxh]lookups?\b", r"\bpivot\s+tables?\b", r"\bvba\b", r"\b(excel|vba|spreadsheet|sheets?)\s+macros?\b", r"\bmacros?\s+(in|for)\s+(excel|my\s+spreadsheet|google\s+sheets)\b"), _rx(r"\bformulas?\b", r"\bworkbook\b"), (40, 150), 2.0),
    Category("google_sheets", _rx(r"\bgoogle\s+sheets?\b", r"\bgsheets?\b", r"\bapps\s+script\b"), None, (40, 150), 2.0),
    Category("pdf_documents", _rx(r"\bpdfs?\b", r"\bdocx\b", r"\bocr\b", r"\bword\s+documents?\b"), _rx(r"\bformat(ting)?\s+(a\s+|my\s+)?(document|resume|report)\b", r"\bscanned\b"), (30, 120), 1.5),
    Category("data_cleaning", _rx(r"\bdata\s+entry\b", r"\bdata\s+clean(ing|up)?\b", r"\bclean\s+up\s+(my\s+|a\s+|the\s+|our\s+)?(data|database|list|contacts)\b", r"\bdedup\w*\b", r"\bduplicates?\b", r"\bcustomer\s+(list|database)\b", r"\bmailing\s+list\b"), _rx(r"\bdatabase\b", r"\bcrm\b"), (40, 180), 3.0),
    Category("files_csv", _rx(r"\bcsv\b", r"\borgani[sz]e\s+(my\s+|our\s+|the\s+)?(files|folders|documents|photos)\b", r"\brename\s+(files|folders)\b"), _rx(r"\bfile\s+organi[sz]ation\b"), (30, 120), 2.0),
    Category("computer_help", _rx(r"\bcomputer\s+(help|problem|issue)s?\b", r"\btech\s+support\b", r"\bit\s+support\b", r"\btroubleshoot\w*\b",r"\blaptop\s+(is\s+)?(slow|problem|issue)\b", r"\bset\s?up\s+(my\s+)?(email|printer|router|computer)\b"), _rx(r"\bvirus\b", r"\bprinter\b"), (30, 100), 1.5),
    Category("website", _rx(r"\b(build|make|create|design|fix|update|redo|set\s?up|need)\s+(me\s+)?(a|my|our|the)?\s*(simple|basic|small|new|business)?\s*(website|web\s?site|site|landing\s+page)\b", r"\bwebsite\s+(help|fix|issue|problem|update|design|builder)\b", r"\blanding\s+page\b", r"\bwordpress\b", r"\bsquarespace\b", r"\bwix\b"), _rx(r"\bhtml\b", r"\bcss\b", r"\bweb\s+page\b", r"\bshopify\b"), (80, 250), 4.0),
    Category("dashboard_report", _rx(r"\bdashboards?\b", r"\bpower\s?bi\b", r"\blooker\s+studio\b"), _rx(r"\bmonthly\s+report\b", r"\bsales\s+report\b"), (60, 200), 3.0),
    Category("automation_script", _rx(r"\bautomat(e|ion|ing)\s+(this|my|a|the|our|some)?\s*\w*\s*(task|process|workflow|report|emails?|spreadsheet|data|job)s?\b", r"\bpython\s+script\b", r"\bzapier\b", r"\bscript\s+(to|that)\s+(automate|convert|rename|extract|download|merge|sort|clean)\b"), _rx(r"\brepetitive\s+task\b"), (60, 200), 3.0),
    Category("extraction", _rx(r"\bextract(ing|ion)?\s+(data|info|information|text|tables?)\b", r"\bdata\s+extraction\b", r"\bscrape\b", r"\bscraping\b", r"\btranscribe\b"), None, (40, 150), 2.5),
]

OFFER_TITLE = _rx(r"\[\s*for\s*hire\s*\]", r"\[\s*offer(ing)?\s*\]", r"\bfor\s+hire\b", r"\[\s*fh\s*\]", r"\[\s*(wts|selling|for\s+sale)\s*\]")
# Signals that the poster wants to pay/hire someone, as opposed to asking for free advice.
HIRE_INTENT = _rx(r"\b(will|willing\s+to|happy\s+to|can)\s+pay\b", r"\bpay\s+(someone|a\s+person|you|for)\b", r"\bhire\s+(someone|a|an)\b", r"\bpaid\s+(task|gig|job|help)\b", r"\bbudget\b", r"\$\s?\d", r"\bcompensat\w+\b",
                  r"\bknow\s+(of\s+)?(someone|anyone|a\s+person)\s+(who|that)\s+(can|could|does)\b", r"\brecommend\s+(someone|a\s+person|anyone)\b", r"\b(need|looking\s+for)\s+someone\s+to\b", r"\bfreelancer\b")
REQUEST_TITLE = _rx(r"\[\s*hiring\s*\]", r"\[\s*task\s*\]", r"\[\s*request\s*\]", r"\[\s*paid\s*\]")
OFFER_TEXT = _rx(r"\bi\s+(will|can)\s+(do|build|create|design|make|help\s+you)\b", r"\bhire\s+me\b", r"\bmy\s+services\b", r"\bi\s+offer\b", r"\bi'?m\s+offering\b", r"\bmy\s+portfolio\b", r"\bavailable\s+for\s+(work|hire|projects)\b", r"\bmy\s+rates?\b")
REQUEST_TEXT = _rx(r"\bneed\s+(some\s+)?(help|someone|a\s+person)\b", r"\blooking\s+for\s+(someone|a\s+person|help|a\s+freelancer)\b", r"\bcan\s+(someone|anyone)\b", r"\banyone\s+(know|able|willing)\b", r"\bhelp\s+me\b", r"\bwilling\s+to\s+pay\b", r"\bwill\s+pay\b", r"\bi\s+need\b")
PAYMENT_TEXT = _rx(r"\$\s?\d", r"\bpay(ing|ment)?\b", r"\bbudget\b", r"\bcompensat\w+\b", r"\bpaid\b", r"\b\d+\s?(usd|dollars)\b", r"\bhourly\b", r"\bper\s+hour\b")

EXCLUSIONS: list[tuple[str, re.Pattern]] = [
    ("full_time_employment", _rx(r"\bfull[\s-]?time\b", r"\bsalary\b", r"\b401\s?k\b", r"\bw-?2\b", r"\bbenefits\s+package\b", r"\bpermanent\s+(role|position)\b")),
    ("unpaid", _rx(r"\[\s*unpaid\s*\]", r"\bunpaid\s+(position|role|internship|opportunity|gig|project|work)\b", r"\b(this|it)\s+is\s+unpaid\b",
                   r"\bfor\s+exposure\b", r"\bvolunteers?\s+(needed|wanted)\b", r"\bwilling\s+to\s+volunteer\b", r"\bequity\s+only\b", r"\bno\s+pay\b")),
    ("internship", _rx(r"\binternship\b")),
    ("mlm_affiliate_referral", _rx(r"\bmlm\b", r"\bnetwork\s+marketing\b", r"\baffiliate\b", r"\breferral\s+(link|code|bonus|program)\b", r"\brefer\s+a\s+friend\b", r"\bsign\s?up\s+(bonus|and\s+earn)\b")),
    ("survey_signup", _rx(r"\bsurveys?\s+for\s+(cash|money)\b", r"\bpaid\s+surveys?\b", r"\bpaid\s+sign\s?ups?\b", r"\bparticipants?\s+needed\b", r"\bresearch\s+study\b")),
    ("crypto_promo", _rx(r"\bairdrop\b", r"\btoken\s+(launch|presale)\b", r"\bnft\s+(mint|project)\b", r"\bmeme\s?coin\b")),
    ("ai_training_recruitment", _rx(r"\b(ai|llm)\s+(training|trainer|tutor)s?\b.*\b(apply|join|hiring|remote)\b", r"\bdata\s+annotat\w+\b", r"\boutlier\.ai\b", r"\bdataannotation\b", r"\bremotasks\b")),
    ("suspicious_request", _rx(r"\bfake\s+(id|reviews?|documents?|degree|diploma)\b", r"\bhack\s+(into|my\s+ex|an?\s+account)\b",
                               r"\bbypass\w*\s+(the\s+)?(paywall|drm|licen[cs]\w*|activation|verification|2fa)\b", r"\breverse[\s-]?engineer\w*\b", r"\bkeygen\b",
                               r"\bcrack\w*\s+(the\s+|a\s+)?(software|licen[cs]\w*|key|password|account|app)\b", r"\b(get\s+into|access)\s+(someone|my\s+(ex|partner|wife|husband))'?s?\s+(account|phone|email)\b",
                               r"\b(buy|sell)\s+(reddit|google|yelp|amazon)\s+(accounts|reviews|upvotes)\b",
                               r"\bactivation\s+lock\b", r"\bicloud\s+(bypass|unlock|removal)\b", r"\bunlock\s+(a|an|this|the)?\s*(stolen|found|locked)\s+(iphone|phone|device)\b", r"\b(do|take)\s+my\s+(exam|test|homework|assignment|quiz)\b")),
]

COMPLEXITY_HIGH = _rx(r"\bfull[\s-]?stack\b", r"\bmobile\s+app\b", r"\b(ios|android)\s+app\b", r"\bsaas\b", r"\bmarketplace\s+(app|platform|website)\b", r"\bmachine\s+learning\b", r"\btrain\s+(a|an|my)\s+(ai|model)\b", r"\bblockchain\b", r"\bsmart\s+contract\b", r"\blong[\s-]term\b", r"\bongoing\s+(work|role|position)\b", r"\bcrm\s+from\s+scratch\b", r"\bapp\s+like\b")
COMPLEXITY_LOW = _rx(r"\bsimple\b", r"\bquick\b", r"\bsmall\s+(task|job|project)\b", r"\bbasic\b", r"\bone[\s-]time\b", r"\bshould\s+be\s+easy\b")
REMOTE = _rx(r"\bremote(ly)?\b", r"\bonline\b", r"\bvirtual(ly)?\b", r"\bfrom\s+anywhere\b", r"\bover\s+(zoom|teams|screen\s?share)\b")
LOCAL = _rx(r"\bin[\s-]person\b", r"\bon[\s-]?site\b", r"\bcome\s+(to|over)\b", r"\bmy\s+(house|home|office|shop|store)\b", r"\blocal\s+(only|person|help)\b", r"\bnear\s+me\b")
# Just the amount as written ("$50", "$40-60", "$15/hr+"), never surrounding sentence text.
BUDGET = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?(?:\s?(?:-|–|to)\s?\$?\s?\d[\d,]*)?\+?(?:\s?(?:/|per|an?)\s?(?:hr|hour|task|job|day|week|month)\b)?\+?", re.IGNORECASE)


def detect_intent(post: RawPost) -> str:
    if OFFER_TITLE.search(post.title):
        return "offer"
    if REQUEST_TITLE.search(post.title):
        return "request"
    text = f"{post.title}\n{post.body}"
    offer, request = bool(OFFER_TEXT.search(text)), bool(REQUEST_TEXT.search(text))
    if request and not offer:
        return "request"
    if offer and not request:
        return "offer"
    if request and offer:
        # "I need ... I will pay" is common; prefer request when the title asks.
        return "request" if REQUEST_TEXT.search(post.title) else "unclear"
    return "unclear"


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
ASK_PHRASE = _rx(r"\bneed", r"\bhelp\b", r"\blooking\s+for\b", r"\bsomeone\b", r"\banyone\b", r"\bwant\s+(to|a|someone)\b", r"\bwould\s+like\b", r"\bpay\b", r"\btask\b", r"\bhiring\b", r"\bjob\b")


def task_focus(post: RawPost) -> str:
    """Title plus the sentences that actually ask for something.

    Matching categories only here stops incidental mentions ("our channel dashboard",
    "she wants to excel in her field") from making unrelated posts look relevant.
    """
    asks = [s for s in _SENTENCE.split(post.body) if ASK_PHRASE.search(s)]
    return "\n".join([post.title, *asks])


def match_categories(text: str) -> tuple[list[str], int]:
    """Strong (specific) matches decide relevance; weak ones only add to an existing match."""
    strong = [c.name for c in CATEGORIES if c.strong.search(text)]
    if not strong:
        return [], 0
    weak = [c.name for c in CATEGORIES if c.name not in strong and c.weak and c.weak.search(text)]
    return strong + weak, 2 * len(strong) + len(weak)


def detect_remote(text: str, allowed_areas: list[str], digital: bool) -> str:
    lowered = f" {text.lower()} "
    if LOCAL.search(text):
        return "local-ok" if any(a in lowered for a in allowed_areas) else "local-outside"
    if REMOTE.search(text):
        return "remote"
    return "remote-likely" if digital else "unknown"


def extract_budget(text: str) -> str | None:
    m = BUDGET.search(text)
    return " ".join(m.group(0).split()) if m else None


def subreddit_of(post: RawPost) -> str:
    return post.source_detail.lower().removeprefix("r/") if post.source == "reddit" else ""


def analyze(post: RawPost, settings: dict, repost_count: int = 0, age_hours: float | None = None) -> Assessment:
    fcfg = settings.get("filters", {})
    text = f"{post.title}\n{post.body}"
    intent = detect_intent(post)
    categories, strength = match_categories(task_focus(post))
    scam = scam_mod.assess(post.title, post.body, repost_count)
    remote = detect_remote(text, fcfg.get("allowed_local_areas", []), digital=bool(categories))
    budget = extract_budget(text)

    if COMPLEXITY_HIGH.search(text):
        complexity = "high"
    elif COMPLEXITY_LOW.search(text) or len(post.body) < 600:
        complexity = "low"
    else:
        complexity = "medium"

    reject = None
    if subreddit_of(post) in {b.lower() for b in fcfg.get("blocked_subreddits", [])}:
        reject = "blocked_community"
    for code, rx in EXCLUSIONS:
        if reject is None and rx.search(text):
            reject = code
    if reject is None:
        if intent == "offer":
            reject = "offering_services"
        elif not categories:
            reject = "no_target_category"
        elif remote == "local-outside":
            reject = "physical_presence_outside_area"
        elif age_hours is not None and age_hours > fcfg.get("max_post_age_days", 7) * 24:
            reject = "too_old"
        elif len(post.body.strip()) < fcfg.get("min_body_chars", 15) and strength < 2:
            reject = "too_vague"

    # --- suitability (rule-based estimate, 0-100) ---
    reasons: list[str] = []
    score = 40
    cat_points = min(20, strength * 7)
    score += cat_points
    reasons.append(f"+{cat_points} matches target categories: {', '.join(categories) or 'none'}")
    if REQUEST_TITLE.search(post.title):
        score += 15
        reasons.append("+15 explicitly tagged as a paid task/hiring request")
    elif intent == "request":
        score += 10
        reasons.append("+10 reads as a request for help")
    else:
        score -= 15
        reasons.append("-15 unclear whether this is a request")
    if PAYMENT_TEXT.search(text):
        score += 10
        reasons.append("+10 mentions payment or budget")
    if 80 <= len(post.body) <= 2500:
        score += 10
        reasons.append("+10 problem is described in some detail")
    elif len(post.body) < 40:
        score -= 10
        reasons.append("-10 very little detail")
    if remote in ("remote", "remote-likely"):
        score += 5
        reasons.append(f"+5 {remote}")
    if complexity == "high":
        score -= 25
        reasons.append("-25 looks like a large or long-term project")
    sub = subreddit_of(post)
    task_subs = {s.lower() for s in fcfg.get("task_subreddits", [])}
    if sub in {s.lower() for s in fcfg.get("free_help_subreddits", [])}:
        score -= 25
        reasons.append(f"-25 posted in r/{sub}, where people usually expect free advice")
    # Manual imports were picked by you, so they skip this; every automatic source outside
    # a task community must show hiring intent.
    manual = post.source.endswith("(manual)")
    if not manual and sub not in task_subs and not HIRE_INTENT.search(text):
        if score > 60:
            reasons.append("capped at 60: general community post with no sign the poster wants to pay or hire someone")
        score = min(score, 60)
    if reject:
        score = min(score, 30)
        reasons.append(f"capped: rejected ({reject})")
    suitability = max(0, min(100, score))

    est_low = est_high = est_hours = None
    if categories:
        primary = next(c for c in CATEGORIES if c.name == categories[0])
        est_low, est_high = primary.price
        mult = {"low": 1.0, "medium": 1.6, "high": 3.0}[complexity]
        est_low, est_high = int(est_low * mult), int(est_high * mult)
        # Execution + communication (0.75h) + QA/revisions (40%) + delivery (0.25h)
        est_hours = round(primary.hours * mult * 1.4 + 1.0, 1)

    return Assessment(
        intent=intent,
        categories=categories,
        passed=reject is None,
        reject_reason=reject,
        suitability=suitability,
        suitability_reasons=reasons,
        remote=remote,
        complexity=complexity,
        advertised_budget=budget,
        est_price_low=est_low,
        est_price_high=est_high,
        est_hours=est_hours,
        scam=scam,
    )
