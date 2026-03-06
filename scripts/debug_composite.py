"""调试脚本：在 Gift Panel 上标注 slot 边界 + 放置测试礼物，输出到 output/debug_composite.png。

用法: python3 scripts/debug_composite.py [礼物图片路径]
不传参数时使用纯红色方块作为占位。
"""

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

# 从 postprocess.py 导入参数，保持单一来源
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.postprocess import _ASSETS_DIR, _PANEL_TEMPLATE, _GIFT_SLOT_CENTER, _GIFT_SLOT_SIZE


def main():
    if not _PANEL_TEMPLATE.exists():
        print(f"底图模板不存在: {_PANEL_TEMPLATE}")
        sys.exit(1)

    panel = Image.open(_PANEL_TEMPLATE).convert("RGBA")
    draw = ImageDraw.Draw(panel)

    # 计算 slot 边界框
    cx, cy = _GIFT_SLOT_CENTER
    half = _GIFT_SLOT_SIZE // 2
    slot_box = (cx - half, cy - half, cx + half, cy + half)

    # 画 slot 边界框（绿色虚线效果：用绿色矩形）
    draw.rectangle(slot_box, outline="lime", width=2)
    # 画十字中心线
    draw.line([(cx - 10, cy), (cx + 10, cy)], fill="lime", width=1)
    draw.line([(cx, cy - 10), (cx, cy + 10)], fill="lime", width=1)

    # 加载或创建测试礼物图
    if len(sys.argv) > 1:
        gift_path = Path(sys.argv[1])
        if not gift_path.exists():
            print(f"礼物图片不存在: {gift_path}")
            sys.exit(1)
        gift = Image.open(gift_path).convert("RGBA")
    else:
        # 纯红色半透明方块作为占位
        gift = Image.new("RGBA", (200, 200), (255, 0, 0, 180))

    # 等比缩放（同 postprocess.py 逻辑）
    gift.thumbnail((_GIFT_SLOT_SIZE, _GIFT_SLOT_SIZE), Image.LANCZOS)
    paste_x = cx - gift.width // 2
    paste_y = cy - gift.height // 2
    panel.paste(gift, (paste_x, paste_y), gift)

    # 标注实际粘贴区域（红色边框）
    actual_box = (paste_x, paste_y, paste_x + gift.width, paste_y + gift.height)
    draw.rectangle(actual_box, outline="red", width=2)

    # 标注间距数值
    # 与 slot 边界的间距
    pad_left = paste_x - slot_box[0]
    pad_top = paste_y - slot_box[1]
    pad_right = slot_box[2] - (paste_x + gift.width)
    pad_bottom = slot_box[3] - (paste_y + gift.height)
    info = f"gift: {gift.width}x{gift.height} | pad: L={pad_left} T={pad_top} R={pad_right} B={pad_bottom}"
    draw.text((10, panel.height - 30), info, fill="yellow")

    # 输出
    output_dir = Path(__file__).resolve().parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    out_path = output_dir / "debug_composite.png"
    panel.save(out_path)
    print(f"调试图已保存: {out_path}")
    print(f"  slot 边界: {slot_box}")
    print(f"  礼物尺寸: {gift.width}x{gift.height}")
    print(f"  间距 (L/T/R/B): {pad_left}/{pad_top}/{pad_right}/{pad_bottom}")


if __name__ == "__main__":
    main()
