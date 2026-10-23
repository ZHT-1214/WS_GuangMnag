"""Local YOSO inference sidecar for obstacle, object, and scene queries."""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


CLASS_ZH = {
    "person": "人", "bicycle": "自行车", "car": "汽车", "motorcycle": "摩托车",
    "airplane": "飞机", "bus": "公交车", "train": "火车", "truck": "卡车",
    "boat": "船", "traffic light": "红绿灯", "fire hydrant": "消防栓",
    "stop sign": "停车标志", "parking meter": "停车收费表", "bench": "长椅",
    "bird": "鸟", "cat": "猫", "dog": "狗", "horse": "马", "sheep": "羊",
    "cow": "牛", "elephant": "大象", "bear": "熊", "zebra": "斑马",
    "giraffe": "长颈鹿", "backpack": "背包", "umbrella": "雨伞", "handbag": "手提包",
    "suitcase": "行李箱", "bottle": "瓶子", "wine glass": "酒杯", "cup": "杯子",
    "fork": "叉子", "knife": "刀", "spoon": "勺子", "bowl": "碗",
    "banana": "香蕉", "apple": "苹果", "sandwich": "三明治", "orange": "橙子",
    "broccoli": "西兰花", "carrot": "胡萝卜", "hot dog": "热狗", "pizza": "披萨",
    "donut": "甜甜圈", "cake": "蛋糕", "chair": "椅子", "couch": "沙发",
    "potted plant": "盆栽", "bed": "床", "dining table": "餐桌", "toilet": "马桶",
    "tv": "电视", "laptop": "笔记本电脑", "mouse": "鼠标", "remote": "遥控器",
    "keyboard": "键盘", "cell phone": "手机", "microwave": "微波炉", "oven": "烤箱",
    "toaster": "烤面包机", "sink": "水槽", "refrigerator": "冰箱", "book": "书",
    "clock": "钟", "vase": "花瓶", "scissors": "剪刀", "teddy bear": "玩具熊",
    "hair drier": "吹风机", "toothbrush": "牙刷", "road": "道路",
    "pavement-merged": "路面", "stairs": "楼梯", "tree-merged": "树木",
    "sky-other-merged": "天空", "grass-merged": "草地", "building-other-merged": "建筑",
    "wall-brick": "砖墙", "floor-wood": "木地板", "floor-other-merged": "地面",
    "water-other": "水面", "window-other": "窗户", "door-stuff": "门",
    "rug-merged": "地毯", "shelf": "架子", "table-merged": "桌子",
    "tie": "领带", "frisbee": "飞盘", "skis": "双板滑雪板",
    "snowboard": "单板滑雪板", "sports ball": "球", "kite": "风筝",
    "baseball bat": "棒球棒", "baseball glove": "棒球手套",
    "skateboard": "滑板", "surfboard": "冲浪板", "tennis racket": "网球拍",
    "banner": "横幅", "blanket": "毯子", "bridge": "桥", "cardboard": "纸板",
    "counter": "柜台", "curtain": "窗帘", "flower": "花", "fruit": "水果",
    "gravel": "碎石", "house": "房屋", "light": "灯", "mirror-stuff": "镜子",
    "net": "网", "pillow": "枕头", "platform": "站台", "playingfield": "运动场",
    "railroad": "铁轨", "river": "河流", "roof": "屋顶", "sand": "沙地",
    "sea": "海面", "snow": "积雪", "tent": "帐篷", "towel": "毛巾",
    "wall-stone": "石墙", "wall-tile": "瓷砖墙", "wall-wood": "木墙",
    "window-blind": "百叶窗", "fence-merged": "围栏", "ceiling-merged": "天花板",
    "cabinet-merged": "柜子", "mountain-merged": "山", "dirt-merged": "泥土地面",
    "paper-merged": "纸", "food-other-merged": "食物", "rock-merged": "岩石",
    "wall-other-merged": "墙面",
}

ITEM_ALIASES = {
    "水杯": "cup", "杯子": "cup", "杯": "cup", "水瓶": "bottle", "瓶子": "bottle",
    "手机": "cell phone", "电话": "cell phone", "书本": "book", "书": "book",
    "椅子": "chair", "凳子": "chair", "桌子": "dining table", "餐桌": "dining table",
    "沙发": "couch", "遥控器": "remote", "钥匙": "key", "背包": "backpack",
    "包": "handbag", "手提包": "handbag", "马桶": "toilet", "电视": "tv",
    "电脑": "laptop", "笔记本电脑": "laptop", "香蕉": "banana", "苹果": "apple",
    "橙子": "orange", "狗": "dog", "猫": "cat", "人": "person", "长椅": "bench",
}


class YosoBackend:
    def __init__(self) -> None:
        root = Path(os.getenv("WSPLUS_YOSO_ROOT", "/root/YOSO")).resolve()
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root / "projects"))
        from yoso_seg4 import Navigater, YOSOSeg

        config = Path(os.getenv(
            "WSPLUS_YOSO_CONFIG",
            root / "projects/YOSO/configs/coco/panoptic-segmentation/YOSO-R50.yaml",
        ))
        checkpoint = Path(os.getenv(
            "WSPLUS_YOSO_CHECKPOINT",
            "/root/ws/modle1/yoso_res50_coco (1).pth",
        ))
        if not config.is_file() or not checkpoint.is_file():
            raise FileNotFoundError("YOSO config or checkpoint is missing")
        self.model = YOSOSeg(str(config), str(checkpoint))
        self.navigator = Navigater()
        self.lock = threading.Lock()
        self.labels = list(self.model.metadata.stuff_classes)

    def _decode(self, payload: bytes):
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("uploaded frame is not a valid image")
        height, width = image.shape[:2]
        if max(height, width) > 1280:
            scale = 1280 / max(height, width)
            image = cv2.resize(image, (int(width * scale), int(height * scale)))
        return image

    def obstacle(self, payload: bytes):
        image = self._decode(payload)
        with self.lock:
            predictions, mask = self.model.inference(image)
            segments = predictions["panoptic_seg"][1]
            stairs = any(int(segment["category_id"]) == 106 for segment in segments)
            direction = self.navigator.run(mask.copy(), image.copy()) if mask is not None else "none"
        directions = {"left": "left", "ahead": "forward", "right": "right"}
        normalized = directions.get(str(direction), "unknown")
        if stairs:
            message = "检测到楼梯区域，请停下确认"
        elif normalized == "unknown":
            message = "未能判断可行方向，请停下确认"
        else:
            message = {
                "left": "模型建议左侧方向，请结合盲杖确认",
                "right": "模型建议右侧方向，请结合盲杖确认",
                "forward": "模型建议前方方向，请结合盲杖确认",
            }[normalized]
        return {
            "direction": normalized,
            "stairs": stairs,
            "message": message,
            "model": "YOSO-COCO",
        }

    def find(self, payload: bytes, requested_item: str):
        import cv2

        item = requested_item.strip()
        canonical = ITEM_ALIASES.get(item, item.casefold())
        item = CLASS_ZH.get(canonical, item)
        if canonical not in self.labels:
            return {
                "found": False,
                "item": item,
                "position": "none",
                "message": f"暂不支持识别“{item}”，请换成常见物品名称",
                "supported": False,
            }
        image = self._decode(payload)
        with self.lock:
            mask = self.model.get_item_mask(image, canonical)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return {
                "found": False,
                "item": item,
                "position": "none",
                "message": f"当前画面没有识别到{item}",
                "supported": True,
            }
        contour = max(contours, key=cv2.contourArea)
        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            return {"found": False, "item": item, "position": "none", "message": f"当前画面没有识别到{item}", "supported": True}
        height, width = mask.shape[:2]
        x = int(moments["m10"] / moments["m00"])
        y = int(moments["m01"] / moments["m00"])
        column = min(x * 3 // width, 2)
        row = min(y * 3 // height, 2)
        positions = (("left_up", "mid_up", "right_up"), ("left_mid", "mid_mid", "right_mid"), ("left_bottom", "mid_bottom", "right_bottom"))
        position = positions[row][column]
        zh_position = {
            "left_up": "左上方", "mid_up": "上方", "right_up": "右上方",
            "left_mid": "左侧", "mid_mid": "画面中间", "right_mid": "右侧",
            "left_bottom": "左下方", "mid_bottom": "下方", "right_bottom": "右下方",
        }[position]
        return {
            "found": True,
            "item": item,
            "position": position,
            "message": f"{item}在画面{zh_position}",
            "supported": True,
        }

    def describe(self, payload: bytes):
        image = self._decode(payload)
        with self.lock:
            predictions, _ = self.model.inference(image)
            panoptic, segments = predictions["panoptic_seg"]
            panoptic = panoptic.to("cpu")
            height, width = panoptic.shape
            detected = []
            for segment in segments:
                category = int(segment["category_id"])
                if category < 0 or category >= len(self.labels):
                    continue
                area = int((panoptic == int(segment["id"])).sum().item())
                ratio = area / float(height * width)
                if ratio < 0.015:
                    continue
                label = self.labels[category]
                name = CLASS_ZH.get(label, "未分类物体")
                detected.append((ratio, name))
        names = list(dict.fromkeys(name for _, name in sorted(detected, reverse=True)))[:6]
        description = "画面中可识别到：" + "、".join(names) if names else "当前画面未能识别出明确场景类别"
        return {"description": description, "objects": names, "model": "YOSO-COCO"}


class Handler(BaseHTTPRequestHandler):
    backend: YosoBackend | None = None
    startup_error: str | None = None

    def _json(self, status: int, body):
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if urlparse(self.path).path != "/health":
            self._json(404, {"detail": "接口不存在"})
            return
        self._json(200, {
            "status": "ok" if self.backend else "degraded",
            "inference_ready": self.backend is not None,
            "inference_error": self.startup_error,
        })

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in {"/v1/vision/obstacle", "/v1/vision/find", "/v1/vision/describe"}:
            self._json(404, {"detail": "接口不存在"})
            return
        if self.backend is None:
            self._json(503, {"detail": "视觉识别模型尚未就绪"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 8 * 1024 * 1024:
                self._json(413, {"detail": "图片大小必须在 1 字节到 8 MB 之间"})
                return
            payload = self.rfile.read(size)
            if parsed.path.endswith("/obstacle"):
                result = self.backend.obstacle(payload)
            elif parsed.path.endswith("/find"):
                item = parse_qs(parsed.query).get("item", [""])[0]
                if not item.strip():
                    self._json(400, {"detail": "请提供要寻找的物品名称"})
                    return
                result = self.backend.find(payload, item)
            else:
                result = self.backend.describe(payload)
            self._json(200, result)
        except ValueError as error:
            self._json(400, {"detail": str(error)})
        except Exception as error:
            self._json(500, {"detail": "视觉识别失败，请检查云端日志"})

    def log_message(self, format, *args):
        print("YOSO", self.address_string(), format % args, flush=True)


def main() -> None:
    try:
        Handler.backend = YosoBackend()
    except Exception as error:
        Handler.startup_error = f"{type(error).__name__}: {error}"
    host = os.getenv("WSPLUS_YOSO_HOST", "127.0.0.1")
    port = int(os.getenv("WSPLUS_YOSO_PORT", "8001"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"YOSO sidecar listening on {host}:{port}; ready={Handler.backend is not None}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
