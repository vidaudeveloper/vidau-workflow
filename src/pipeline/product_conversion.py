"""产品转化方式：由产品名称、上架状态、conversion_method 字段决定 CTA 话术。"""

from typing import Any

CONVERSION_METHOD_GUIDE: dict[str, str] = {
    "视频挂链": (
        "转化方式：视频挂链（TikTok 视频下方商品链接/购物车）。"
        "CTA 口播须引导用户点击视频下方链接或购物车入口购买；"
        "禁止引导去官网搜索、禁止说 Bio 链接、禁止提 AfterPay/分期（除非产品价格信息明确支持）。"
        "可结合活动价、coupon、限时折扣话术。"
    ),
    "Bio引流": (
        "转化方式：Bio引流（不挂车）。视频不挂商品链；"
        "CTA 口播引导用户点击主页 Bio 中的链接；"
        "禁止说视频下方链接、购物车、shop link below this video。"
    ),
    "橱窗商品卡": (
        "转化方式：橱窗/商品卡。CTA 引导用户通过账号橱窗或商品卡入口购买。"
    ),
}


def resolve_conversion_method(product: dict[str, Any] | None) -> str:
    if not product:
        return "视频挂链"
    explicit = (product.get("conversion_method") or "").strip()
    if explicit:
        return explicit
    blob = f"{product.get('name', '')} {product.get('listing_status', '')}".lower()
    if any(k in blob for k in ("不挂车", "bio引流", "引流到bio", "bio放", "kickstarter")):
        return "Bio引流"
    if "橱窗" in blob or "商品卡" in blob:
        return "橱窗商品卡"
    return "视频挂链"


def build_conversion_context(product: dict[str, Any] | None) -> str:
    method = resolve_conversion_method(product)
    parts = [
        CONVERSION_METHOD_GUIDE.get(method, CONVERSION_METHOD_GUIDE["视频挂链"]),
        f"当前产品转化方式: {method}",
    ]
    if not product:
        return "\n".join(parts)
    if method == "视频挂链":
        price_parts = []
        if product.get("daily_price"):
            price_parts.append(f"日常价 {product['daily_price']}")
        if product.get("promo_price"):
            price_parts.append(f"活动价 {product['promo_price']}")
        if product.get("purchase_link"):
            price_parts.append(f"商品链接 {product['purchase_link']}")
        if price_parts:
            parts.append("产品价格参考（口播可用）: " + "；".join(price_parts))
    elif method == "Bio引流":
        if product.get("listing_status"):
            parts.append(product["listing_status"])
        if product.get("purchase_link"):
            parts.append(f"Bio/众筹链接参考: {product['purchase_link']}")
    else:
        if product.get("daily_price"):
            parts.append(f"日常价 {product['daily_price']}")
        if product.get("promo_price"):
            parts.append(f"活动价 {product['promo_price']}")
        if product.get("purchase_link"):
            parts.append(f"链接 {product['purchase_link']}")
    return "\n".join(parts)


def pricing_context_for_product(
    product: dict[str, Any] | None, *, conversion_method: str = ""
) -> str:
    if not product:
        return ""
    method = conversion_method or resolve_conversion_method(product)
    parts = []
    if product.get("daily_price"):
        parts.append(f"日常价 {product['daily_price']}")
    if product.get("promo_price"):
        parts.append(f"活动价 {product['promo_price']}")
    if product.get("listing_status") and method != "视频挂链":
        parts.append(product["listing_status"])
    if product.get("purchase_link") and method != "Bio引流":
        parts.append(f"链接 {product['purchase_link']}")
    return "；".join(parts)
