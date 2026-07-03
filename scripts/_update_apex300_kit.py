"""一次性更新 Apex300+Charger 2+DC Hub 产品信息与参考图。"""
import json
import shutil
import uuid
from pathlib import Path

import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "workflow.db"
UPLOADS = ROOT / "data" / "uploads" / "products"

PRODUCT_ID = "d18ed461"
KIT_SRC = UPLOADS / "apex300_kit_overview.png"

SPECS = """【套装型号】Apex 300 + Charger 2 + DC Hub D1 三件套

【参考图顺序（固定配置）】
1. 套装全貌平铺图 — 主机 + Charger 2 + DC Hub D1 + 线缆同画面；Nano Banana 首帧主参考，按此还原各模块外形与相对比例
2. Apex 300 主机正面 — 4×AC 输出口、LCD、按键区
3. 三件套一体组装图 — 主机居中，左侧 Charger 2、右侧 DC Hub D1 侧挂/锁扣一体
4. 套装平铺分件图 — Charger 2 / DC Hub D1 与主机分开展示（便于识别各配件轮廓）
5. 主机侧面大电流口区 — 仅供接口布局理解，成片禁止此类插口特写

【套装模块与相对大小】
- Apex 300 主机（Hero）：最大件，深灰金属质感矩形机体，宽约 40–45 cm 级；画面宽度约占 50–60%
- Charger 2：中等偏小横置模块，宽约 15–18 cm；宽度约为主机的 35–40%；顶面斜纹/碳纤维纹理 + BLUETTI 标识
- DC Hub D1：中等偏小矩形模块，宽约 12–15 cm；宽度约为主机的 30–35%；顶面 BLUETTI 标识 + 旋钮/按钮 + 圆形 DC 口 + 分线头

【画面构图 / 摆放（首帧 & 分镜默认）】
- Apex 300 主机居中略靠前，作为视觉焦点
- Charger 2 置于主机左侧（观众视角左），底边与主机对齐或略后
- DC Hub D1 置于主机右侧（观众视角右），与 Charger 2 对称
- 三件套须同场景、同景深出现，Medium-wide 中远景，确保三件全貌入画、小配件不被裁切
- 14 口布局：正面 4×AC + LCD/按键；侧面 USB/DC/RV 大口径；Charger 2 / DC Hub 各带扩展 DC 口 — 成片只展示整机与中远景，禁止任何插口特写
- 禁止：插插座、手插插头、AC/USB/DC 端口单独放大、线缆接入演示、360° 环绕运镜

【Apex 300 主机 | 3840W | 2764.8Wh】
- 外观：深灰大型方体，前面板放射纹理底纹，顶部/侧面集成提手
- 正面中央：AC OUTPUT 120V/3840W Pure-Sine-Wave，NEMA 5-20 美标 AC 插座 ×4（黑色弹簧盖，上 2 下 2，各 20A Max，两两一组各 1920W）
- 正面上部：电压选择 120V/240V（左上橙色拨动）、ECO/AC 键（绿灯）、充电模式 Silent/Auto/Turbo（右上橙色拨动）、圆形绿色电源键、中央 LCD（电量%、DC/AC 输入输出 W、剩余时间）
- 左侧面：USB-C ×1、USB-A ×1、圆形 DC 输出口 ×1、通讯/并机口 ×1、大号垂直盖板口 ×3（RV/大电流/扩展）
- 右侧面：大号垂直盖板口 ×2（高功率 AC IN/OUT 或扩展）

【Charger 2 模块】
- 深灰横置矩形，顶面斜纹纹理 + BLUETTI 标识，侧面安装耳/螺丝孔，左上角绿色指示灯
- 与 Apex 300 左侧锁扣/侧挂一体，扩展车载/太阳能等充电能力

【DC Hub D1 模块】
- 深灰紧凑矩形，顶面 BLUETTI 标识 + 两个方形按钮/指示灯 + 多个圆形 DC 输出口
- 自带分线头（红黑鳄鱼夹等），与 Apex 300 右侧锁扣/侧挂一体，扩展 DC 配电

【可演示交互（按键/屏幕级，禁止插电）】
- 按 Apex 300 电源键、AC 输出键、电压选择键、充电模式键
- 展示 LCD 电量、输入/输出功率读数
- 轻触 DC Hub D1 旋钮/按钮（不展示端口内部）
- 手轻触套装三件套示意「一体性/模块化」（可选，中远景、不遮挡产品 Logo）

【分镜 interaction_beats 建议（供 LLM 与首帧 Nano Banana 读取）】
- 0–3s | action: 三件套同场景亮相 — Apex 300 居中，Charger 2 左、DC Hub D1 右，Medium-wide 静态构图 | camera: 中远景固定机位
- 3–8s | action: 手轻触三件套外轮廓示意一体性，或按 Apex 电源键点亮 LCD | camera: 缓慢 Push-in，仍保持三件全貌
- 8–12s | action: 展示 LCD 电量/功率读数，切换 ECO 或充电模式拨动（不插线） | camera: 正面中景，4×AC 区可见但不特写
- 12–15s | action: 镜头略拉远，三件套并排/一体组装形态留悬念 | camera: 轻微 Pull-back
- 15–18s | action: 承接 — 展示侧挂一体组装后的宽体轮廓 | camera: 3/4 侧角度，禁止环绕
- 18–24s | action: 强调 Charger 2 + DC Hub 与主机协同（按键/屏幕，无插线） | camera: 同场景慢节奏
- 24–30s | action: 收束三件套整机 + CTA 留白区 | camera: 稳定中远景

【product_understanding 建议字段】
- hero_product: Apex 300
- allowed_accessories: ["Charger 2", "DC Hub D1"]
- forbidden_in_frame: ["插插座", "插口特写", "手插插头", "道具上的 BLUETTI Logo", "360° 环绕运镜"]
"""

def main() -> None:
    kit_id = uuid.uuid4().hex
    kit_dest = UPLOADS / f"{kit_id}.png"
    shutil.copy2(KIT_SRC, kit_dest)

    image_urls = [
        f"/uploads/products/{kit_id}.png",
        "/uploads/products/754fd3734f524a86b24d32b6bbce74c1.png",
        "/uploads/products/95b7d37525fd4d21b01d7583538d2323.png",
        "/uploads/products/ba5d2e2114e24ab98f8068141df27f07.webp",
        "/uploads/products/bd1c204f623b4bec9800e1c40f0ccd93.png",
    ]

    conn = sqlite3.connect(DB)
    conn.execute(
        """
        UPDATE products
        SET image_url = ?,
            image_urls_json = ?,
            product_specs = ?,
            product_specs_confirmed = 1,
            product_specs_draft = ?
        WHERE id = ?
        """,
        (
            image_urls[0],
            json.dumps(image_urls, ensure_ascii=False),
            SPECS,
            SPECS,
            PRODUCT_ID,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT name, image_urls_json, length(product_specs) FROM products WHERE id=?",
        (PRODUCT_ID,),
    ).fetchone()
    conn.close()
    print("Updated:", row[0])
    print("Images:", row[1])
    print("Specs length:", row[2])

if __name__ == "__main__":
    main()
