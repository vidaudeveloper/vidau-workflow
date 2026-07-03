"""根据账号人设推断 Seedance 口播音色描述，并为 Edge TTS 分配稳定音色。"""

from __future__ import annotations

import zlib
from typing import Any

from src.pipeline.brand_profile import BrandProfile
from src.pipeline.workflow_language import is_spanish

_DEFAULT_HINT = (
    "Clear natural American English voiceover, confident and friendly, moderate pace."
)

_DEFAULT_HINT_ES = (
    "Voz en español latinoamericano (México), natural y cercana, ritmo moderado."
)


def brand_voice_pronunciation(brand: BrandProfile | None, language: str | None = None) -> str:
    """品牌发音指令（口播怎么读品牌名）。无品牌或无发音覆盖时返回空串。"""
    if not brand or not brand.has_brand or not brand.has_pronunciation:
        return ""
    if is_spanish(language):
        return f"Pronunciar la marca {brand.display} como «{brand.spoken}»."
    return (
        f"Pronounce the brand {brand.display} as '{brand.spoken}' in audio only "
        f"(keep the on-screen spelling {brand.display})."
    )

# Edge TTS en-US
TTS_FEMALE_VOICES = (
    "en-US-JennyNeural",
    "en-US-AriaNeural",
    "en-US-MichelleNeural",
    "en-US-SaraNeural",
    "en-US-EmmaNeural",
)
TTS_MALE_VOICES = (
    "en-US-GuyNeural",
    "en-US-ChristopherNeural",
    "en-US-EricNeural",
    "en-US-DavisNeural",
    "en-US-JasonNeural",
)
TTS_NEUTRAL_VOICES = (
    "en-US-JennyNeural",
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-US-MichelleNeural",
    "en-US-ChristopherNeural",
    "en-US-SaraNeural",
    "en-US-EricNeural",
    "en-US-EmmaNeural",
)

# Edge TTS es-MX（拉美 TikTok）
TTS_ES_FEMALE_VOICES = (
    "es-MX-DaliaNeural",
    "es-MX-NuriaNeural",
    "es-MX-CandelaNeural",
    "es-MX-RenataNeural",
)
TTS_ES_MALE_VOICES = (
    "es-MX-JorgeNeural",
    "es-MX-CecilioNeural",
    "es-MX-LibertoNeural",
    # Gerardo 在部分网络/文案下易触发 NoAudioReceived，仅作末位回退
    "es-MX-GerardoNeural",
)
TTS_ES_NEUTRAL_VOICES = (
    "es-MX-DaliaNeural",
    "es-MX-JorgeNeural",
    "es-MX-NuriaNeural",
    "es-MX-GerardoNeural",
)


def _account_blob(account: dict[str, Any] | None) -> str:
    if not account:
        return ""
    return " ".join(
        str(account.get(k, "") or "")
        for k in (
            "display_name",
            "username",
            "blogger_type",
            "positioning",
            "persona_style",
            "page_packaging",
            "bio",
            "content_directions",
        )
    ).lower()


def infer_gender_from_account(account: dict[str, Any] | None) -> str:
    blob = _account_blob(account)
    if not blob:
        return "neutral"
    if any(k in blob for k in ("mom", "mother", "妈妈", "female creator", "温柔", "细心", "wife", "woman")):
        return "female"
    if any(k in blob for k in ("dad", "father", "爸爸", "守护", "garage", "husband", "brother")):
        return "male"
    return "neutral"


def infer_gender_from_profile(voice_profile: dict[str, Any] | None) -> str:
    profile = voice_profile or {}
    gender = str(profile.get("gender", "")).lower().strip()
    if gender in ("female", "male"):
        return gender
    tone = " ".join(
        str(profile.get(k, "") or "") for k in ("tone", "age_tone", "seedance_hint", "prompt_hint")
    ).lower()
    if any(k in tone for k in ("female", "woman", "mom", "mother", "gentle", "she ")):
        return "female"
    if any(k in tone for k in ("male", "man", "dad", "father", " his ")):
        return "male"
    return "neutral"


def resolve_tts_voice(
    voice_profile: dict[str, Any] | None = None,
    *,
    account: dict[str, Any] | None = None,
    account_id: str = "",
    override: str = "",
    language: str | None = None,
) -> str:
    """按人设 + 账号 + 语言稳定选 Edge TTS 音色。"""
    if override.strip():
        return override.strip()

    from src.config import get_settings

    settings = get_settings()
    if settings.tts_voice.strip():
        return settings.tts_voice.strip()

    profile = dict(voice_profile or {})
    if profile.get("tts_voice"):
        return str(profile["tts_voice"]).strip()

    lang = language or profile.get("language") or (account or {}).get("language") or "英语"
    spanish = is_spanish(lang)

    gender = infer_gender_from_profile(profile)
    if gender == "neutral" and account:
        gender = infer_gender_from_account(account)

    if spanish:
        if gender == "female":
            pool = TTS_ES_FEMALE_VOICES
        elif gender == "male":
            pool = TTS_ES_MALE_VOICES
        else:
            pool = TTS_ES_NEUTRAL_VOICES
    elif gender == "female":
        pool = TTS_FEMALE_VOICES
    elif gender == "male":
        pool = TTS_MALE_VOICES
    else:
        pool = TTS_NEUTRAL_VOICES

    seed = (account_id or (account or {}).get("id", "") or profile.get("tone", "") or "default").strip()
    if spanish:
        seed = f"es:{seed}"
    idx = zlib.crc32(seed.encode("utf-8")) % len(pool)
    return pool[idx]


def _voice_pool_for_language(language: str | None, gender: str) -> tuple[str, ...]:
    spanish = is_spanish(language)
    if spanish:
        if gender == "female":
            return TTS_ES_FEMALE_VOICES
        if gender == "male":
            return TTS_ES_MALE_VOICES
        return TTS_ES_NEUTRAL_VOICES
    if gender == "female":
        return TTS_FEMALE_VOICES
    if gender == "male":
        return TTS_MALE_VOICES
    return TTS_NEUTRAL_VOICES


def iter_tts_voice_candidates(
    voice_profile: dict[str, Any] | None = None,
    *,
    account: dict[str, Any] | None = None,
    account_id: str = "",
    override: str = "",
    language: str | None = None,
) -> list[str]:
    """主音色 + 同语种备选，供 Edge TTS 遇 NoAudioReceived 时自动回退。"""
    primary = resolve_tts_voice(
        voice_profile,
        account=account,
        account_id=account_id,
        override=override,
        language=language,
    )
    profile = dict(voice_profile or {})
    lang = language or profile.get("language") or (account or {}).get("language") or "英语"
    gender = infer_gender_from_profile(profile)
    if gender == "neutral" and account:
        gender = infer_gender_from_account(account)
    pool = _voice_pool_for_language(lang, gender)
    chain = [primary]
    for voice in pool:
        if voice not in chain:
            chain.append(voice)
    return chain


def build_voice_profile(
    account: dict[str, Any] | None,
    *,
    language: str | None = None,
) -> dict[str, str]:
    lang = language or (account or {}).get("language") or "英语"
    spanish = is_spanish(lang)

    if not account:
        profile = {
            "gender": "neutral",
            "tone": "friendly, clear",
            "age_tone": "拉美 30s" if spanish else "",
            "language": lang,
            "seedance_hint": _DEFAULT_HINT_ES if spanish else _DEFAULT_HINT,
            "prompt_hint": (
                "Voz: narrador en español latinoamericano, ritmo natural."
                if spanish
                else "Voice: clear American English narrator, natural pacing."
            ),
        }
        profile["tts_voice"] = resolve_tts_voice(profile, language=lang)
        return profile

    blob = _account_blob(account)

    if any(k in blob for k in ("mom", "mother", "妈妈", "female creator", "温柔", "细心")):
        profile = {
            "gender": "female",
            "tone": "warm, gentle, caring",
            "age_tone": "30s-40s latina mom" if spanish else "30s-40s American mom",
            "language": lang,
            "seedance_hint": (
                "Voz femenina mexicana cálida y suave, tono maternal, ritmo tranquilo."
                if spanish
                else (
                    "Warm gentle American English female voice, soft and reassuring, "
                    "natural motherly tone, calm moderate pace, empathetic delivery."
                )
            ),
            "prompt_hint": (
                "Voz femenina latina cálida (persona mamá)."
                if spanish
                else "0-15s voice: warm gentle American female narrator (mom persona), "
                "soft caring tone, not robotic or announcer-like."
            ),
        }
    elif any(k in blob for k in ("dad", "father", "爸爸", "守护")):
        profile = {
            "gender": "male",
            "tone": "steady, practical, reassuring",
            "age_tone": "30s-45s latino dad" if spanish else "30s-45s American dad",
            "language": lang,
            "seedance_hint": (
                "Voz masculina mexicana clara y práctica, tono de papá confiable, ritmo moderado."
                if spanish
                else (
                    "Calm confident American English male voice, practical dad tone, "
                    "clear trustworthy delivery, moderate pace."
                )
            ),
            "prompt_hint": (
                "Voz masculina latina práctica (persona papá)."
                if spanish
                else "0-15s voice: calm American male narrator (dad persona), "
                "practical and reassuring, not salesy."
            ),
        }
    elif any(k in blob for k in ("outdoor", "露营", "camp", "adventure", "户外")):
        profile = {
            "gender": "neutral",
            "tone": "energetic, upbeat, outdoorsy",
            "age_tone": "young adult",
            "language": lang,
            "seedance_hint": (
                "Voz latina amigable y enérgica, estilo aventura al aire libre, conversacional."
                if spanish
                else (
                    "Upbeat friendly American English voice, light outdoor adventure energy, "
                    "natural conversational pace."
                )
            ),
            "prompt_hint": (
                "Voz latina animada, estilo outdoor."
                if spanish
                else "Voice: upbeat American narrator, casual outdoor vibe."
            ),
        }
    else:
        profile = {
            "gender": infer_gender_from_account(account),
            "tone": "friendly, clear",
            "age_tone": "",
            "language": lang,
            "seedance_hint": _DEFAULT_HINT_ES if spanish else _DEFAULT_HINT,
            "prompt_hint": (
                "Voz clara en español latinoamericano para contenido de producto."
                if spanish
                else "Voice: clear American English narrator matching product social content."
            ),
        }

    profile["tts_voice"] = resolve_tts_voice(profile, account=account, language=lang)
    return profile


def voice_hint_for_seedance(
    profile: dict[str, str] | None,
    *,
    brand: BrandProfile | None = None,
    language: str | None = None,
) -> str:
    base = (profile or {}).get("seedance_hint") or _DEFAULT_HINT
    base = base.strip()
    lang = language or (profile or {}).get("language")
    pron = brand_voice_pronunciation(brand, lang)
    return f"{base} {pron}".strip() if pron else base
