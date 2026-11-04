"""
Part B — supported languages, their edge-tts voices, and fixed warning text
used when the AI is unavailable. Amharic text is reviewed by a native speaker;
the other languages still need a native-speaker check.

'script' is a regex for the writing system an AI answer must contain, so an
answer in the wrong language is rejected (None = Latin script, not checked).
"""

DEFAULT_LANGUAGE = 'en'

_ETHIOPIC = r'[ሀ-፿]'
_DEVANAGARI = r'[ऀ-ॿ]'
_CJK = r'[一-鿿]'

LANGUAGES = {
    'en': {'name': 'English', 'voice': 'en-US-AriaNeural',
           'ai_name': 'English', 'script': None},
    'am': {'name': 'አማርኛ (Amharic)', 'voice': 'am-ET-MekdesNeural',
           'ai_name': "Amharic (አማርኛ), written in Ge'ez (Ethiopic) script", 'script': _ETHIOPIC},
    'es': {'name': 'Español (Spanish)', 'voice': 'es-US-PalomaNeural',
           'ai_name': 'Spanish (español)', 'script': None},
    'fr': {'name': 'Français (French)', 'voice': 'fr-FR-DeniseNeural',
           'ai_name': 'French (français)', 'script': None},
    'zh': {'name': '中文 (Mandarin)', 'voice': 'zh-CN-XiaoxiaoNeural',
           'ai_name': 'Simplified Chinese (简体中文)', 'script': _CJK},
    'hi': {'name': 'हिन्दी (Hindi)', 'voice': 'hi-IN-SwaraNeural',
           'ai_name': 'Hindi (हिन्दी), written in Devanagari script', 'script': _DEVANAGARI},
    'ne': {'name': 'नेपाली (Nepali)', 'voice': 'ne-NP-HemkalaNeural',
           'ai_name': 'Nepali (नेपाली), written in Devanagari script', 'script': _DEVANAGARI},
}

# key → {lang: text}. Use {placeholders} for values.
MESSAGES: dict = {
    # ── Red flags (one per scam category) ──
    'flag.false_urgency': {
        'en': 'Pressure to pay right away',
        'am': 'ወዲያውኑ እንዲከፍሉ ያስገድዳል',
        'es': 'Te presiona para pagar de inmediato',
        'fr': 'Vous pousse à payer tout de suite',
        'zh': '催促你立即付款',
        'hi': 'तुरंत भुगतान करने का दबाव डालता है',
        'ne': 'तुरुन्तै भुक्तानी गर्न दबाब दिन्छ',
    },
    'flag.threat_account_limited': {
        'en': 'Threatens that your account is limited or suspended',
        'am': 'መለያዎ እንደታገደ ወይም እንደተገደበ ያስፈራራል',
        'es': 'Amenaza con que tu cuenta está limitada o suspendida',
        'fr': 'Menace que votre compte est limité ou suspendu',
        'zh': '威胁说你的账户已被限制或冻结',
        'hi': 'धमकी देता है कि आपका खाता सीमित या निलंबित कर दिया गया है',
        'ne': 'तपाईंको खाता सीमित वा निलम्बित भएको भनेर धम्की दिन्छ',
    },
    'flag.impersonation': {
        'en': 'Pretends to be PayPal or customer support',
        'am': 'ራሱን እንደ PayPal ወይም የደንበኞች አገልግሎት ያስመስላል',
        'es': 'Se hace pasar por PayPal o por atención al cliente',
        'fr': 'Se fait passer pour PayPal ou le service client',
        'zh': '冒充 PayPal 或客服',
        'hi': 'PayPal या ग्राहक सहायता होने का दिखावा करता है',
        'ne': 'आफूलाई PayPal वा ग्राहक सेवा भएको देखाउँछ',
    },
    'flag.credential_request': {
        'en': 'Asks for your password, a code, or login details',
        'am': 'የይለፍ ቃልዎን፣ ኮድ ወይም የመግቢያ መረጃዎን ይጠይቃል',
        'es': 'Pide tu contraseña, un código o tus datos de acceso',
        'fr': 'Demande votre mot de passe, un code ou vos identifiants',
        'zh': '索要你的密码、验证码或登录信息',
        'hi': 'आपका पासवर्ड, कोड या लॉगिन विवरण माँगता है',
        'ne': 'तपाईंको पासवर्ड, कोड वा लगइन विवरण माग्छ',
    },
    'flag.gift_card_or_crypto': {
        'en': 'Asks for gift cards or cryptocurrency',
        'am': 'በስጦታ ካርድ ወይም በክሪፕቶ ገንዘብ እንዲከፍሉ ይጠይቃል',
        'es': 'Pide tarjetas de regalo o criptomonedas',
        'fr': 'Demande des cartes cadeaux ou des cryptomonnaies',
        'zh': '要求用礼品卡或加密货币付款',
        'hi': 'गिफ्ट कार्ड या क्रिप्टोकरेंसी माँगता है',
        'ne': 'गिफ्ट कार्ड वा क्रिप्टोकरेन्सी माग्छ',
    },
    'flag.suspicious_link': {
        'en': 'Contains a suspicious link',
        'am': 'አጠራጣሪ ሊንክ ይዟል',
        'es': 'Contiene un enlace sospechoso',
        'fr': 'Contient un lien suspect',
        'zh': '包含可疑链接',
        'hi': 'इसमें एक संदिग्ध लिंक है',
        'ne': 'शंकास्पद लिङ्क समावेश छ',
    },
    'flag.overpayment': {
        'en': 'Overpayment trick: asks you to send money back',
        'am': 'ከልክ በላይ ተከፍሏል ብሎ ገንዘብ እንዲመልሱ ይጠይቃል',
        'es': 'Truco de sobrepago: te pide devolver dinero',
        'fr': "Arnaque au trop-perçu : vous demande de renvoyer de l'argent",
        'zh': '多付款骗局：要求你退回钱款',
        'hi': 'ज़्यादा भुगतान की चाल: आपसे पैसे वापस भेजने को कहता है',
        'ne': 'बढी भुक्तानीको चाल: पैसा फिर्ता पठाउन भन्छ',
    },
    'flag.mismatched_names': {
        'en': "The recipient doesn't match who the message claims to be",
        'am': 'ተቀባዩ መልእክቱ ከሚለው ስም ጋር አይዛመድም',
        'es': 'El destinatario no coincide con quien dice ser el mensaje',
        'fr': "Le destinataire ne correspond pas à l'expéditeur annoncé",
        'zh': '收款人与消息自称的身份不符',
        'hi': 'प्राप्तकर्ता उस नाम से मेल नहीं खाता जो संदेश में बताया गया है',
        'ne': 'प्राप्तकर्ता सन्देशले दाबी गरेको नामसँग मेल खाँदैन',
    },
    'flag.join': {'en': '; ', 'am': '፤ ', 'es': '; ', 'fr': ' ; ', 'zh': '；', 'hi': '; ', 'ne': '; '},

    # ── Scam explanations (keyword fallback) ──
    'scam.no_text': {
        'en': 'There was no message or invoice to check.',
        'am': 'የሚመረመር መልእክት ወይም ደረሰኝ የለም።',
        'es': 'No había ningún mensaje ni factura que revisar.',
        'fr': "Il n'y avait aucun message ni facture à vérifier.",
        'zh': '没有需要检查的消息或账单。',
        'hi': 'जाँचने के लिए कोई संदेश या बिल नहीं था।',
        'ne': 'जाँच गर्नुपर्ने कुनै सन्देश वा बिल थिएन।',
    },
    'scam.none': {
        'en': 'We found no common scam signs in this message.',
        'am': 'በዚህ መልእክት ውስጥ የተለመዱ የማጭበርበር ምልክቶች አላገኘንም።',
        'es': 'No encontramos señales comunes de estafa en este mensaje.',
        'fr': "Nous n'avons trouvé aucun signe d'arnaque courant dans ce message.",
        'zh': '我们在这条消息中没有发现常见的诈骗迹象。',
        'hi': 'हमें इस संदेश में धोखाधड़ी के आम संकेत नहीं मिले।',
        'ne': 'यो सन्देशमा ठगीका सामान्य संकेतहरू भेटिएनन्।',
    },
    'scam.some': {
        'en': 'This message has some warning signs: {flags}. Make sure you really know this person before you pay.',
        'am': 'ይህ መልእክት አንዳንድ የማስጠንቀቂያ ምልክቶች አሉት፦ {flags}። ከመክፈልዎ በፊት ይህን ሰው በትክክል እንደሚያውቁት ያረጋግጡ።',
        'es': 'Este mensaje tiene algunas señales de alerta: {flags}. Asegúrate de conocer de verdad a esta persona antes de pagar.',
        'fr': "Ce message présente des signaux d'alerte : {flags}. Assurez-vous de bien connaître cette personne avant de payer.",
        'zh': '这条消息有一些警告信号：{flags}。付款前请确认你真的认识这个人。',
        'hi': 'इस संदेश में कुछ चेतावनी संकेत हैं: {flags}। भुगतान करने से पहले पक्का कर लें कि आप इस व्यक्ति को सच में जानते हैं।',
        'ne': 'यो सन्देशमा केही चेतावनीका संकेतहरू छन्: {flags}। भुक्तानी गर्नुअघि तपाईं यो व्यक्तिलाई साँच्चै चिन्नुहुन्छ भनी निश्चित गर्नुहोस्।',
    },
    'scam.many': {
        'en': 'This looks like a scam: {flags}. PayPal will never ask you to pay this way. Do not send money.',
        'am': 'ይህ ማጭበርበር ይመስላል፦ {flags}። PayPal በዚህ መንገድ እንዲከፍሉ በፍጹም አይጠይቅም። ገንዘብ አይላኩ።',
        'es': 'Esto parece una estafa: {flags}. PayPal nunca te pedirá pagar de esta forma. No envíes dinero.',
        'fr': "Cela ressemble à une arnaque : {flags}. PayPal ne vous demandera jamais de payer de cette façon. N'envoyez pas d'argent.",
        'zh': '这看起来是诈骗：{flags}。PayPal 绝不会要求你这样付款。请不要转账。',
        'hi': 'यह धोखाधड़ी लगती है: {flags}। PayPal आपसे कभी भी इस तरह भुगतान करने को नहीं कहेगा। पैसे न भेजें।',
        'ne': 'यो ठगी जस्तो देखिन्छ: {flags}। PayPal ले तपाईंलाई यसरी भुक्तानी गर्न कहिल्यै भन्दैन। पैसा नपठाउनुहोस्।',
    },

    # ── Final verdicts (risk engine) ──
    'verdict.LOW': {
        'en': 'Low risk. This payment looks safe.',
        'am': 'ዝቅተኛ ስጋት። ይህ ክፍያ ደህንነቱ የተጠበቀ ይመስላል።',
        'es': 'Riesgo bajo. Este pago parece seguro.',
        'fr': 'Risque faible. Ce paiement semble sûr.',
        'zh': '低风险。这笔付款看起来是安全的。',
        'hi': 'कम जोखिम। यह भुगतान सुरक्षित लगता है।',
        'ne': 'कम जोखिम। यो भुक्तानी सुरक्षित देखिन्छ।',
    },
    'verdict.MEDIUM': {
        'en': 'Medium risk. Please confirm this payment is really you.',
        'am': 'መካከለኛ ስጋት። እባክዎ ይህን ክፍያ የሚፈጽሙት እርስዎ መሆንዎን ያረጋግጡ።',
        'es': 'Riesgo medio. Confirma que eres tú quien hace este pago.',
        'fr': "Risque moyen. Confirmez que c'est bien vous qui faites ce paiement.",
        'zh': '中等风险。请确认这笔付款确实是你本人操作。',
        'hi': 'मध्यम जोखिम। कृपया पुष्टि करें कि यह भुगतान आप ही कर रहे हैं।',
        'ne': 'मध्यम जोखिम। कृपया यो भुक्तानी तपाईं आफैंले गर्दै हुनुहुन्छ भनी पुष्टि गर्नुहोस्।',
    },
    'verdict.HIGH': {
        'en': 'High risk. QUICK Guard blocked this payment.',
        'am': 'ከፍተኛ ስጋት። QUICK Guard ይህን ክፍያ አግዷል።',
        'es': 'Riesgo alto. QUICK Guard bloqueó este pago.',
        'fr': 'Risque élevé. QUICK Guard a bloqué ce paiement.',
        'zh': '高风险。QUICK Guard 已拦截这笔付款。',
        'hi': 'उच्च जोखिम। QUICK Guard ने यह भुगतान रोक दिया है।',
        'ne': 'उच्च जोखिम। QUICK Guard ले यो भुक्तानी रोकेको छ।',
    },

    # ── Location ──
    'travel.minutes': {'en': '{n} minutes', 'am': '{n} ደቂቃ', 'es': '{n} minutos', 'fr': '{n} minutes',
                       'zh': '{n} 分钟', 'hi': '{n} मिनट', 'ne': '{n} मिनेट'},
    'travel.hours': {'en': '{n} hours', 'am': '{n} ሰዓት', 'es': '{n} horas', 'fr': '{n} heures',
                     'zh': '{n} 小时', 'hi': '{n} घंटे', 'ne': '{n} घण्टा'},
    'travel.impossible': {
        'en': 'This payment comes from {to_city}, {km} km from your last payment in {from_city} just {elapsed} ago. '
              'Nobody can travel that fast, so someone else may be using your account.',
        'am': 'ይህ ክፍያ የመጣው ከ{to_city} ነው፤ ይህም ከ{elapsed} በፊት ከፈጸሙት ክፍያ ቦታ ({from_city}) {km} ኪ.ሜ ይርቃል። '
              'ማንም በዚህ ፍጥነት መጓዝ አይችልም፤ ሌላ ሰው መለያዎን እየተጠቀመ ሊሆን ይችላል።',
        'es': 'Este pago viene de {to_city}, a {km} km de tu último pago en {from_city} hace solo {elapsed}. '
              'Nadie puede viajar tan rápido, así que otra persona podría estar usando tu cuenta.',
        'fr': 'Ce paiement vient de {to_city}, à {km} km de votre dernier paiement à {from_city} il y a seulement {elapsed}. '
              "Personne ne peut voyager aussi vite : quelqu'un d'autre utilise peut-être votre compte.",
        'zh': '这笔付款来自{to_city}，距离你 {elapsed}前在{from_city}的上一笔付款 {km} 公里。'
              '没有人能移动得这么快，可能有其他人正在使用你的账户。',
        'hi': 'यह भुगतान {to_city} से आ रहा है, जो सिर्फ़ {elapsed} पहले {from_city} में किए गए आपके पिछले भुगतान से {km} किमी दूर है। '
              'कोई भी इतनी तेज़ी से यात्रा नहीं कर सकता, इसलिए हो सकता है कोई और आपका खाता इस्तेमाल कर रहा हो।',
        'ne': 'यो भुक्तानी {to_city} बाट आएको हो, जुन {elapsed} अघि मात्र {from_city} मा गरिएको तपाईंको अघिल्लो भुक्तानीबाट {km} किमी टाढा छ। '
              'कोही पनि यति छिटो यात्रा गर्न सक्दैन, त्यसैले अरू कसैले तपाईंको खाता प्रयोग गरिरहेको हुन सक्छ।',
    },
    'travel.fast': {
        'en': 'This payment is {km} km from your last one in {from_city}, which is unusually far for the time since then.',
        'am': 'ይህ ክፍያ ካለፈው ክፍያዎ ቦታ ({from_city}) {km} ኪ.ሜ ይርቃል፤ ይህም ከዚያ ወዲህ ባለው ጊዜ አንጻር ያልተለመደ ርቀት ነው።',
        'es': 'Este pago está a {km} km del anterior en {from_city}, una distancia inusual para el tiempo que ha pasado.',
        'fr': 'Ce paiement est à {km} km du précédent à {from_city}, ce qui est inhabituel pour le temps écoulé.',
        'zh': '这笔付款距离你上一笔在{from_city}的付款 {km} 公里，就所经过的时间而言，这个距离不寻常。',
        'hi': 'यह भुगतान {from_city} में किए गए आपके पिछले भुगतान से {km} किमी दूर है, जो बीते समय के हिसाब से असामान्य रूप से दूर है।',
        'ne': 'यो भुक्तानी {from_city} मा गरिएको तपाईंको अघिल्लो भुक्तानीबाट {km} किमी टाढा छ, जुन बितेको समयको तुलनामा असामान्य दूरी हो।',
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
