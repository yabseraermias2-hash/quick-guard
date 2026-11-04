"""
Part B — supported languages, their edge-tts voices, and fixed warning text
used when the AI is unavailable. Amharic text is reviewed by a native speaker.
"""

DEFAULT_LANGUAGE = 'en'

LANGUAGES = {
    'en': {'name': 'English', 'voice': 'en-US-AriaNeural', 'ai_name': 'English'},
    'am': {'name': 'አማርኛ (Amharic)', 'voice': 'am-ET-MekdesNeural',
           'ai_name': 'Amharic (አማርኛ), written in Ge\'ez (Ethiopic) script'},
}

# key → {lang: text}. Use {placeholders} for values.
MESSAGES: dict = {
    # ── Red flags (one per scam category) ──
    'flag.false_urgency': {
        'en': 'Pressure to pay right away',
        'am': 'ወዲያውኑ እንዲከፍሉ ያስገድዳል',
    },
    'flag.threat_account_limited': {
        'en': 'Threatens that your account is limited or suspended',
        'am': 'መለያዎ እንደታገደ ወይም እንደተገደበ ያስፈራራል',
    },
    'flag.impersonation': {
        'en': 'Pretends to be PayPal or customer support',
        'am': 'ራሱን እንደ PayPal ወይም የደንበኞች አገልግሎት ያስመስላል',
    },
    'flag.credential_request': {
        'en': 'Asks for your password, a code, or login details',
        'am': 'የይለፍ ቃልዎን፣ ኮድ ወይም የመግቢያ መረጃዎን ይጠይቃል',
    },
    'flag.gift_card_or_crypto': {
        'en': 'Asks for gift cards or cryptocurrency',
        'am': 'በስጦታ ካርድ ወይም በክሪፕቶ ገንዘብ እንዲከፍሉ ይጠይቃል',
    },
    'flag.suspicious_link': {
        'en': 'Contains a suspicious link',
        'am': 'አጠራጣሪ ሊንክ ይዟል',
    },
    'flag.overpayment': {
        'en': 'Overpayment trick: asks you to send money back',
        'am': 'ከልክ በላይ ተከፍሏል ብሎ ገንዘብ እንዲመልሱ ይጠይቃል',
    },
    'flag.mismatched_names': {
        'en': "The recipient doesn't match who the message claims to be",
        'am': 'ተቀባዩ መልእክቱ ከሚለው ስም ጋር አይዛመድም',
    },
    'flag.join': {'en': '; ', 'am': '፤ '},

    # ── Scam explanations (keyword fallback) ──
    'scam.no_text': {
        'en': 'There was no message or invoice to check.',
        'am': 'የሚመረመር መልእክት ወይም ደረሰኝ የለም።',
    },
    'scam.none': {
        'en': 'We found no common scam signs in this message.',
        'am': 'በዚህ መልእክት ውስጥ የተለመዱ የማጭበርበር ምልክቶች አላገኘንም።',
    },
    'scam.some': {
        'en': 'This message has some warning signs: {flags}. Make sure you really know this person before you pay.',
        'am': 'ይህ መልእክት አንዳንድ የማስጠንቀቂያ ምልክቶች አሉት፦ {flags}። ከመክፈልዎ በፊት ይህን ሰው በትክክል እንደሚያውቁት ያረጋግጡ።',
    },
    'scam.many': {
        'en': 'This looks like a scam: {flags}. PayPal will never ask you to pay this way. Do not send money.',
        'am': 'ይህ ማጭበርበር ይመስላል፦ {flags}። PayPal በዚህ መንገድ እንዲከፍሉ በፍጹም አይጠይቅም። ገንዘብ አይላኩ።',
    },

    # ── Final verdicts (risk engine) ──
    'verdict.LOW': {
        'en': 'Low risk. This payment looks safe.',
        'am': 'ዝቅተኛ ስጋት። ይህ ክፍያ ደህንነቱ የተጠበቀ ይመስላል።',
    },
    'verdict.MEDIUM': {
        'en': 'Medium risk. Please confirm this payment is really you.',
        'am': 'መካከለኛ ስጋት። እባክዎ ይህን ክፍያ የሚፈጽሙት እርስዎ መሆንዎን ያረጋግጡ።',
    },
    'verdict.HIGH': {
        'en': 'High risk. QUICK Guard blocked this payment.',
        'am': 'ከፍተኛ ስጋት። QUICK Guard ይህን ክፍያ አግዷል።',
    },

    # ── Location ──
    'travel.minutes': {'en': '{n} minutes', 'am': '{n} ደቂቃ'},
    'travel.hours': {'en': '{n} hours', 'am': '{n} ሰዓት'},
    'travel.impossible': {
        'en': 'This payment comes from {to_city}, {km} km from your last payment in {from_city} just {elapsed} ago. '
              'Nobody can travel that fast, so someone else may be using your account.',
        'am': 'ይህ ክፍያ የመጣው ከ{to_city} ነው፤ ይህም ከ{elapsed} በፊት ከፈጸሙት ክፍያ ቦታ ({from_city}) {km} ኪ.ሜ ይርቃል። '
              'ማንም በዚህ ፍጥነት መጓዝ አይችልም፤ ሌላ ሰው መለያዎን እየተጠቀመ ሊሆን ይችላል።',
    },
    'travel.fast': {
        'en': 'This payment is {km} km from your last one in {from_city}, which is unusually far for the time since then.',
        'am': 'ይህ ክፍያ ካለፈው ክፍያዎ ቦታ ({from_city}) {km} ኪ.ሜ ይርቃል፤ ይህም ከዚያ ወዲህ ባለው ጊዜ አንጻር ያልተለመደ ርቀት ነው።',
    },
}


def normalize_language(lang: str | None) -> str:
    """Return a supported language code, falling back to DEFAULT_LANGUAGE."""
    return lang if lang in LANGUAGES else DEFAULT_LANGUAGE


def t(key: str, lang: str, **values) -> str:
    """Look up MESSAGES[key][lang] (falling back to English) and fill placeholders."""
    entry = MESSAGES.get(key, {})
    text = entry.get(normalize_language(lang)) or entry.get(DEFAULT_LANGUAGE) or key
    return text.format(**values) if values else text


def voice_for(lang: str) -> str:
    return LANGUAGES[normalize_language(lang)]['voice']


def all_voices() -> set:
    return {info['voice'] for info in LANGUAGES.values()}
