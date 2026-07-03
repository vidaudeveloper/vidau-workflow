"""根据已上传产品图写入 product_specs（可重复执行）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db.database import init_db
from src.db.repository import Repository

SPECS: dict[str, str] = {
    "Elite 300": """【型号】Elite 300 | 2400W | 3014.4Wh
【外观】深灰方体，前面板碳纤维纹理边框，中央 LCD，底部 BLUETTI 字标；侧面/顶部集成提手。

【正面 · 左区 DC（自上而下）】
- 12V/10A 车充口（圆形，带橡胶盖）×1
- 12V/30A 高电流 DC 输出口（方形，带盖）×1
- DC/PV INPUT 12V-60V/22A/1200W（太阳能/车充输入，带盖）×1

【正面 · 中下 USB 区（标 DC OUTPUT）】
- USB-C 100W ×1（最左）
- USB-A 15W ×2（中间并排）
- USB-C 140W ×1（最右）

【正面 · 右区 AC OUTPUT 120V/2400W Pure-Sine-Wave】
- NEMA TT-30R 圆形 RV 专用 AC 口 ×1（右上方大圆口）
- NEMA 5-15 美标三脚 AC 插座 ×4（2×2 排列，位于 RV 口下方）

【正面 · 中央屏幕与按键】
- LCD：电量%、DC/AC 输入输出功率、剩余时间
- 三键（屏下）：DC（绿灯）| Power | AC（绿灯）

【右侧面 · 充电区（非正面，勿与正面 AC 区混在同一特写）】
- AC INPUT 120V/15A Max（带盖）
- Circuit Protector 125VAC/20A 复位键
- 接地端子

【演示规则】一次只演示 1 种交互；插 AC 只用正面右区 4 个美标孔或 RV 圆口之一；按键只按 DC/AC/Power 之一；禁止欧式孔、禁止正面出现 AC INPUT、禁止臆造第 6 个 AC 孔。""",

    "Apex 300": """【型号】Apex 300 | 3840W | 2764.8Wh
【外观】深灰大型方体，前面板放射纹理底纹，顶部/侧面集成提手。

【正面 · 中央 AC OUTPUT 120V/3840W Pure-Sine-Wave】
- NEMA 5-20 美标 AC 插座 ×4（带黑色弹簧盖；上排 2 个、下排 2 个；每孔标注 20A Max；两两一组各 1920W）

【正面 · 上部控制区】
- 电压选择拨动开关：120V / 240V（左上橙色）
- ECO 键、AC 键（绿灯）
- 充电模式：Silent / Auto / Turbo（右上橙色拨动）
- 电源键（圆形，绿色光环）
- 中央 LCD：电量%、DC/AC 输入输出 W、剩余时间

【左侧面（USB/DC/大口径，非正面）】
- USB-C ×1、USB-A ×1
- 圆形 DC 输出口 ×1
- 通讯/并机口 ×1
- 大号垂直盖板口 ×3（RV/大电流/扩展，带盖）

【右侧面】
- 大号垂直盖板口 ×2（高功率 AC IN/OUT 或扩展）

【演示规则】正面镜头只展示 4×AC 与屏幕/按键；USB 与 RV 大口径口仅在「侧面镜头」出现；一次只插 1 个 AC 孔或只按 1 个键；禁止在正面画 USB 口。""",

    "Apex300+B300K": """【套装】Apex 300 主机 + B300K 扩容电池
【主机面板】同「Apex 300」正面 4×AC + 中央 LCD + 顶部控制键；侧面大口径口用于并机/扩展。

【B300K 扩容包】
- 独立电池模块，不在正面 AC 区出现接口
- 叙事为「加配 B300K 延长续航」时，可展示侧面并机连接，禁止把 B300K 接口画到 Apex 正面

【演示规则】主推 Apex 300 正面 4 AC 插孔演示；扩容场景用侧面连接，一次一种交互。""",

    "Elite 100 V2": """【型号】Elite 100 V2（待上传产品图核对）
【说明】紧凑型便携电源；面板接口以实际上传产品图为准。当前无参考图，脚本/Prompt 禁止特写插口数量，仅允许整机+场景镜头。
【待补】上传正面产品图后补充：AC/USB/DC 数量与位置。""",

    "Elite 100 MiNi": """【型号】Elite 100 MiNi（待上传产品图核对）
【说明】超紧凑机型；无参考图时禁止生成插口特写，仅整机展示+口播。
【待补】上传产品图后补充接口清单。""",

    "FridgePower": """【型号】FridgePower 冰箱备电（待上传产品图核对）
【说明】面向冰箱应急备电场景；无参考图时以「产品整体+冰箱场景」为主，避免 AI 臆造插口特写。
【待补】上传产品图后补充 AC/DC 接口位置与数量。""",
}


def main() -> None:
    init_db()
    repo = Repository()
    updated = 0
    for product in repo.list_products():
        name = product.get("name", "")
        if name not in SPECS:
            continue
        repo.update_product(product["id"], {"product_specs": SPECS[name]})
        updated += 1
        print(f"updated: {name}")
    print(f"done, {updated} products")


if __name__ == "__main__":
    main()
