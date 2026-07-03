"""Per-product brand handling — single source of truth.

The whole pipeline is brand-agnostic: a product carries its own brand (screen
spelling) and an optional pronunciation hint (how the voiceover should say it).
Every stage — script/storyboard prompts, Seedance visual constraints, voice
persona, TTS input, subtitle restore/highlight, kit whitelist — reads brand
wording from here. When a product has NO brand, all helpers degrade to neutral,
brand-free wording so nothing brand-specific leaks in.

Why pronunciation matters: some brand spellings are mispronounced by TTS (the
classic case is "BLUETTI" → say "blue tee"). The voice says `spoken`, but the
on-screen subtitle restores the real spelling `display`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BrandProfile:
    name: str = ""           # on-screen spelling, e.g. "Anker", "BLUETTI" ("" = unbranded)
    pronunciation: str = ""  # how TTS should say it, e.g. "blue tee" ("" = say as written)

    # ---- predicates -----------------------------------------------------
    @property
    def has_brand(self) -> bool:
        return bool(self.name.strip())

    @property
    def display(self) -> str:
        return self.name.strip()

    @property
    def has_pronunciation(self) -> bool:
        return bool(self.pronunciation.strip()) and (
            self.pronunciation.strip().lower() != self.name.strip().lower()
        )

    @property
    def spoken(self) -> str:
        """What the voice should pronounce (pronunciation override or spelling)."""
        p = self.pronunciation.strip()
        return p or self.name.strip()

    # ---- noun phrases (neutral fallbacks when unbranded) ----------------
    def product_noun(self) -> str:
        return f"{self.display} product" if self.has_brand else "the product"

    def unit_noun(self) -> str:
        return f"{self.display} unit" if self.has_brand else "the product unit"

    def module_noun(self) -> str:
        return f"{self.display} module" if self.has_brand else "product module"

    # ---- prompt / constraint snippets -----------------------------------
    def logo_rule_en(self) -> str:
        """Brand-logo placement rule for Seedance / storyboard (English)."""
        if self.has_brand:
            return (
                f"BRAND LOGO RULE: {self.display} name/logo may appear ONLY on the hero "
                "product unit itself (front panel badge). NO logos on mugs, cups, clothing, "
                "tents, bags, tools, walls, packaging, or any other props—use plain "
                "unbranded props only. "
            )
        return (
            "BRAND LOGO RULE: the product's own logo may appear ONLY on the hero product "
            "unit itself. NO third-party or brand logos on mugs, cups, clothing, tents, "
            "bags, tools, walls, packaging, or any other props—use plain unbranded props only. "
        )

    def negative_logo_clause(self) -> str:
        """Clause appended to Seedance negative_prompt."""
        if self.has_brand:
            return f"{self.display} text on walls or furniture (logo only on product unit)"
        return "brand text on walls or furniture (logo only on product unit)"

    def script_instruction(self, language: str | None = None) -> str:
        """Brand line injected into the script-generation user message."""
        from src.pipeline.workflow_language import is_spanish

        if not self.has_brand:
            return (
                "品牌：未指定具体品牌。口播与画面不要编造品牌名；"
                "若产品本体有品牌字标，仅允许出现在产品本体，道具上不得出现任何品牌 Logo。"
            )
        spell = self.display
        if self.has_pronunciation:
            if is_spanish(language):
                say = f"口播读作「{self.spoken}」"
            else:
                say = f'口播读作 "{self.spoken}"（仅发音，屏幕拼写保持 "{spell}"）'
        else:
            say = "口播按拼写自然朗读"
        return (
            f"品牌：{spell}（{say}）。品牌 Logo / 字标仅允许出现在产品本体，"
            "杯子/帐篷/衣物/工具/墙面等道具不得出现任何品牌 Logo。"
        )

    def account_default(self) -> str:
        """Default publishing-account persona when none is set."""
        return f"通用 {self.display} 账号" if self.has_brand else "通用品牌账号"

    # ---- TTS / subtitle helpers -----------------------------------------
    def apply_pronunciation(self, text: str) -> str:
        """Rewrite the brand spelling to its spoken form for TTS input.
        No-op when there is no pronunciation override."""
        if not text or not self.has_pronunciation:
            return text
        spoken = self.pronunciation.strip()
        name = self.name.strip()
        out = text
        for variant in {name, name.upper(), name.lower(), name.title()}:
            if variant:
                out = out.replace(variant, spoken)
        return out

    def protected_tokens(self) -> dict[str, str]:
        """Map spoken-form tokens back to the on-screen spelling (subtitle restore).
        Empty when unbranded or no pronunciation override."""
        if not self.has_brand:
            return {}
        out: dict[str, str] = {self.name.strip().lower(): self.display}
        if self.has_pronunciation:
            out[self.pronunciation.strip().lower()] = self.display
        return out

    def brand_literals(self) -> list[str]:
        """Tokens to brand-highlight on screen. Empty when unbranded."""
        return [self.display] if self.has_brand else []

    def spoken_tokens(self) -> list[str]:
        """Lowercased word tokens of the spoken brand form, for ASR alignment."""
        return [t for t in re.split(r"\s+", self.spoken.lower()) if t]

    def alignment_aliases(self) -> set[str]:
        """Lowercased tokens an ASR engine might emit for the brand word, used to
        tolerate mis-hearings during forced subtitle alignment. Empty = no
        special-casing (safe default)."""
        if not self.has_brand:
            return set()
        aliases: set[str] = {self.name.strip().lower()}
        aliases.update(self.spoken_tokens())
        compact = self.spoken.replace(" ", "").lower()
        if compact:
            aliases.add(compact)
        return aliases


def brand_from_product(product: dict[str, Any] | None) -> BrandProfile:
    if not product:
        return BrandProfile()
    return BrandProfile(
        name=str(product.get("brand") or "").strip(),
        pronunciation=str(product.get("brand_pronunciation") or "").strip(),
    )


def brand_from_spec_json(spec: Any) -> BrandProfile:
    """Recover the brand from a stored storyboard product_spec_json payload."""
    import json

    data = spec
    if isinstance(spec, str):
        try:
            data = json.loads(spec)
        except Exception:  # noqa: BLE001
            return BrandProfile()
    if not isinstance(data, dict):
        return BrandProfile()
    pu = data.get("product_understanding")
    src = pu if isinstance(pu, dict) else data
    return BrandProfile(
        name=str(src.get("brand") or "").strip(),
        pronunciation=str(src.get("brand_pronunciation") or "").strip(),
    )
