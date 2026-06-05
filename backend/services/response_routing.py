"""Greeting/small-talk detection, language hints, and template replies (no web, minimal tokens).
KB similarity tiers: backend.config + backend.services.prompt_builder.
"""

from __future__ import annotations

import re
from typing import Final

# Short standalone greetings / thanks / acks (multilingual). Not for substantive questions.
_GREETING_ONLY = re.compile(
    r"^\s*("
    r"hi+\b|hii+\b|hello+\b|hey+\b|howdy\b|yo\b|sup\b|greetings\b|"
    r"hi\s+there\b|hey\s+there\b|hello\s+there\b|"
    r"hola\b|buenas\b|buenos\s+d[ií]as\b|buenas\s+tardes\b|buenas\s+noches\b|"
    r"salut\b|bonjour\b|bonsoir\b|coucou\b|"
    r"hallo\b|servus\b|moin\b|"
    r"ciao\b|buongiorno\b|buonasera\b|"
    r"ol[aá]\b|oi\b|"
    r"hallo\b|hej\b|"
    r"привет\b|здравствуйте\b|"
    r"你好\b|您好\b|"
    r"こんにちは\b|こんばんは\b|"
    r"안녕\b|안녕하세요\b|"
    r"مرحبا\b|السلام\s+عليكم\b"
    r")[\s!?.。！？]*\s*$",
    re.IGNORECASE,
)

_THANKS_ACK = re.compile(
    r"^\s*("
    r"thanks?\b|thank\s+you\b|thx\b|ty\b|grazie\b|merci\b|danke\b|"
    r"gracias\b|obrigad[oa]\b|gracias\b|"
    r"ok+\b|okay\b|k\b|yes\b|no\b|yep\b|nope\b|sure\b|"
    r"si\b|sí\b|oui\b|non\b|ja\b|nein\b|"
    r"👍|🙏|❤️|✅"
    r")[\s!?.]*\s*$",
    re.IGNORECASE,
)

_HOW_ARE_YOU = re.compile(
    r"^\s*(how\s+are\s+you|what\'?s\s+up|how\'?s\s+it\s+going|wie\s+geht\'?s|"
    r"comment\s+allez-vous|come\s+stai|qué\s+tal|cómo\s+estás)\s*[\?！!\.]?\s*$",
    re.IGNORECASE,
)

_HELP_OPENER = re.compile(
    r"^\s*(help\s*!?\s*|help\s+me\s*[\?!\.]?|ayuda\b|aide\b|hilfe\b|aiuto\b|"
    r"ajuda\b|帮助\b|助けて\b|도와줘\b)\s*$",
    re.IGNORECASE,
)

_GOOD_DAY = re.compile(
    r"^\s*(good\s+)?(morning|afternoon|evening|night|day)\b[\s!,.。]*\s*$",
    re.IGNORECASE,
)

# Word hints -> language code (first match wins after script detection)
_LANG_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(ciao|grazie|prego|buongiorno|buonasera|salve)\b", re.I), "it"),
    (re.compile(r"\b(hola|gracias|buenos|buenas|qué|cómo)\b", re.I), "es"),
    (re.compile(r"\b(bonjour|merci|salut|bonsoir|comment)\b", re.I), "fr"),
    (re.compile(r"\b(hallo|danke|bitte|guten)\b", re.I), "de"),
    (re.compile(r"\b(olá|obrigado|obrigada|bom\s+dia)\b", re.I), "pt"),
    (re.compile(r"\b(hallo|dank|graag|goedemorgen)\b", re.I), "nl"),
    (re.compile(r"\b(cześć|dziękuję|dzień\s+dobry)\b", re.I), "pl"),
    (re.compile(r"\b(привет|спасибо|здравствуйте)\b", re.I), "ru"),
    (re.compile(r"\b(hej|tack|välkommen|god\s+dag)\b", re.I), "sv"),
    (re.compile(r"\b(xin\s+chào|cảm\s+ơn|bạn)\b", re.I), "vi"),
    (re.compile(r"\b(merhaba|teşekkür|yardım)\b", re.I), "tr"),
    (re.compile(r"(नमस्ते|धन्यवाद)"), "hi"),
]


GREETING_REPLY: Final[dict[str, str]] = {
    "en": "Hi! How can I help you today?",
    "es": "¡Hola! ¿En qué puedo ayudarte?",
    "fr": "Bonjour ! Comment puis-je vous aider ?",
    "de": "Hallo! Wie kann ich dir helfen?",
    "it": "Ciao! Come posso aiutarti?",
    "pt": "Olá! Como posso ajudar?",
    "nl": "Hallo! Hoe kan ik je helpen?",
    "pl": "Cześć! Jak mogę pomóc?",
    "ru": "Здравствуйте! Чем могу помочь?",
    "ja": "こんにちは！今日はどのようにお手伝いできますか？",
    "zh": "您好！有什么可以帮您的吗？",
    "ko": "안녕하세요! 무엇을 도와드릴까요?",
    "ar": "مرحبا! كيف يمكنني مساعدتك؟",
}

KB_FALLBACK_REPLY: Final[dict[str, str]] = {
    "en": (
        "I couldn't find specific information about that in our knowledge base. "
        "Could you provide more details, or would you like me to connect you with a human agent?"
    ),
    "es": (
        "No encontré información específica sobre eso en nuestra base de conocimiento. "
        "¿Podrías dar más detalles o prefieres que te conecte con un agente humano?"
    ),
    "fr": (
        "Je n'ai pas trouvé d'informations précises à ce sujet dans notre base de connaissances. "
        "Pouvez-vous préciser votre demande, ou souhaitez-vous être mis en relation avec un agent ?"
    ),
    "de": (
        "Dazu habe ich in unserer Wissensdatenbank keine konkreten Informationen gefunden. "
        "Kannst du mehr Details nennen, oder soll ich dich mit einem Mitarbeiter verbinden?"
    ),
    "it": (
        "Non ho trovato informazioni specifiche al riguardo nella nostra knowledge base. "
        "Puoi fornire più dettagli o preferisci che ti metta in contatto con un operatore?"
    ),
    "pt": (
        "Não encontrei informações específicas sobre isso na nossa base de conhecimento. "
        "Pode dar mais detalhes ou prefere que eu te conecte a um atendente humano?"
    ),
    "nl": (
        "Ik kon daar geen specifieke informatie over vinden in onze kennisbank. "
        "Kun je meer details geven, of wil je doorverbonden worden met een medewerker?"
    ),
    "pl": (
        "Nie znalazłem konkretnych informacji na ten temat w naszej bazie wiedzy. "
        "Czy możesz podać więcej szczegółów, czy mam połączyć Cię z konsultantem?"
    ),
    "ru": (
        "В базе знаний не нашлось конкретной информации по этому вопросу. "
        "Можете уточнить детали или хотите связаться с оператором?"
    ),
    "ja": (
        "ナレッジベースに該当する情報が見つかりませんでした。"
        "詳細を教えていただくか、担当者への接続をご希望ですか？"
    ),
    "zh": (
        "我在知识库中没有找到与此相关的具体信息。"
        "您能提供更多细节吗，或者需要我为您转接人工客服？"
    ),
    "ko": (
        "지식 베이스에서 해당 내용에 대한 구체적인 정보를 찾지 못했습니다. "
        "더 자세히 알려주시거나 상담원 연결을 원하시나요?"
    ),
    "ar": (
        "لم أجد معلومات محددة حول ذلك في قاعدة المعرفة لدينا. "
        "هل يمكنك تقديم المزيد من التفاصيل، أم تفضل التواصل مع موظف؟"
    ),
}


def detect_language_hint(text: str) -> str:
    """Lightweight language hint (no extra dependencies)."""
    t = (text or "").strip()
    if not t:
        return "en"
    if any("\u4e00" <= c <= "\u9fff" for c in t):
        return "zh"
    if any("\u3040" <= c <= "\u30ff" or "\u31f0" <= c <= "\u31ff" for c in t):
        return "ja"
    if any("\uac00" <= c <= "\ud7a3" for c in t):
        return "ko"
    if any("\u0600" <= c <= "\u06ff" for c in t):
        return "ar"
    # Spanish questions/pricing (before Latin keyword collisions with English)
    if re.search(
        r"[\u00bf\u00a1]|"
        r"\b(cuánto|cuánta|cuántos|cuántas|cuanto|cuanta|cómo|dónde|qué|"
        r"por\s+qué|precio|precios|cuesta|muchas\s+gracias|gracias)\b",
        t,
        re.IGNORECASE,
    ):
        return "es"
    if re.search(r"\b(combien|prix|où|comment|pourquoi)\b", t, re.IGNORECASE):
        return "fr"
    if re.search(r"\b(quanto|preço|quanto\s+custa)\b", t, re.IGNORECASE):
        return "pt"
    for pattern, code in _LANG_HINTS:
        if pattern.search(t):
            return code
    return "en"


def is_greeting_or_smalltalk(text: str) -> bool:
    """True for short casual openers, not substantive support questions."""
    t = (text or "").strip()
    if not t:
        return False
    if len(t) > 140:
        return False
    if len(t) > 90 and "?" in t:
        return False
    if _GREETING_ONLY.match(t) or _THANKS_ACK.match(t) or _HOW_ARE_YOU.match(t):
        return True
    if _GOOD_DAY.match(t):
        return True
    if _HELP_OPENER.match(t) and len(re.findall(r"\w+", t.lower())) <= 6:
        return True
    if len(t) <= 24 and re.match(r"^[\s\w\u00c0-\u024f!?.,;:'\"+\-👍🙏❤️✅]+$", t):
        if len(re.findall(r"\w+", t)) <= 4:
            return bool(_THANKS_ACK.match(t) or _GREETING_ONLY.match(t))
    return False


def greeting_reply_for_language(lang: str) -> str:
    return GREETING_REPLY.get(lang, GREETING_REPLY["en"])


def kb_fallback_reply_for_language(lang: str) -> str:
    return KB_FALLBACK_REPLY.get(lang, KB_FALLBACK_REPLY["en"])


_VERY_SHORT_ACK = re.compile(
    r"^\s*("
    r"ok+\b|okay\b|k\b|cool\b|nice\b|got\s+it\b|sounds\s+good\b|understood\b|"
    r"vale\b|perfecto\b|perfect\b|great\b|awesome\b"
    r")[\s!,.]*\s*$",
    re.IGNORECASE,
)


def is_very_short_ack_lightweight(text: str) -> bool:
    """Short acknowledgements without a question — use minimal-token reply path."""
    t = (text or "").strip()
    if not t or len(t) > 44:
        return False
    if "?" in t or "¿" in t:
        return False
    if is_greeting_or_smalltalk(text):
        return False
    if _THANKS_ACK.match(t) or _VERY_SHORT_ACK.match(t):
        return True
    return False


# Substantive support topics — do not treat as "meta" conversational-only.
_SUBSTANTIVE_TOPIC = re.compile(
    r"\b("
    r"bill|billing|invoice|refund|charge|charged|payment|pay|paypal|stripe|card|"
    r"subscription|cancel|renew|plan|tier|price|cost|discount|coupon|promo|"
    r"order|shipping|delivery|tracking|return|warranty|"
    r"account|login|log\s*in|password|email|verify|verification|ban|mute|kick|"
    r"error|bug|crash|lag|down|broken|not\s+working|doesn'?t\s+work|"
    r"how\s+to|where\s+is|when\s+does|why\s+is|what\s+is\s+the|"
    r"robux|discord|nitro|ticket|role|channel|server\s+boost"
    r")\b",
    re.IGNORECASE,
)

_CONVERSATIONAL_HELP_ONLY = re.compile(
    r"^\s*("
    r"(will|would|can|could)\s+you\s+help(\s+me|\s+us)?(\s+please)?\b"
    r"|(will|would)\s+some(one|body)\s+help\s+me\b"
    r"|do\s+you\s+speak\s+[\w\-]+\b"
    r"|are\s+you\s+(a\s+)?(real|human|a\s+bot|there|awake|available)\b"
    r"|is\s+any(one|body)\s+(there|here|around)\b"
    r"|can\s+i\s+(ask|get|have)\s+(you\s+for\s+)?(some\s+)?help\b"
    r"|could\s+i\s+(get|have)\s+(some\s+)?help\b"
    r"|any(one|body)\s+there\b"
    r"|hey[\s,]+(can|could)\s+you\s+help\b"
    r"|¿puedes\s+ayudarme\b"
    r"|peux-tu\s+m['']aider\b"
    r"|kannst\s+du\s+mir\s+helfen\b"
    r"|puoi\s+aiutarmi\b"
    r"|você\s+pode\s+me\s+ajudar\b"
    r")[\s\?！!\.…]*\s*$",
    re.IGNORECASE,
)


def is_conversational_without_kb(text: str) -> bool:
    """Meta / rapport messages answerable without retrieved articles (e.g. 'Will you help me?')."""
    t = (text or "").strip()
    if not t or len(t) > 180:
        return False
    if _SUBSTANTIVE_TOPIC.search(t):
        return False
    if is_greeting_or_smalltalk(text):
        return False
    if is_very_short_ack_lightweight(text):
        return False
    if re.match(
        r"^\s*i\s+need\s+help(\s+please)?\s*[\?.!…]*\s*$", t, re.IGNORECASE
    ) or re.match(r"^\s*need\s+help\s*[\?.!…]*\s*$", t, re.IGNORECASE):
        return True
    return bool(_CONVERSATIONAL_HELP_ONLY.match(t))
