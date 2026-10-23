# -*- coding: utf-8 -*-
"""实验脚本框架：仲裁器消融实验（exp_arbitration）。

在纯 Python 中复现 App 端安全仲裁器的四条规则，喂入离线录制的
方向序列（nav 方向序列 + 障碍方向序列），统计播报次数、方向抖动次数、
冲突改道次数，用于论文 §5.1 E4 的消融对比。

用法：
    python exp_arbitration.py --trace traces/route1.json --out result1.json

输入 trace JSON 格式（可由真机 App 日志或手动标注生成）：
    {
      "nav":  ["forward","forward","left", ...],     # NoMaD 每帧方向
      "obs":  ["forward",null,"left", ...],          # YOSO 每帧方向（null=无响应）
      "stairs": [false, false, true, ...],
      "t":    [0, 0.7, 1.4, ...]                     # 每帧时间戳(秒)
    }
"""
import argparse
import json

# ===== 与 App 端 CloudTopologyNavigationScreen.kt 严格一致的参数 =====
NAV_CONFIRMATIONS = 2
OBSTACLE_CONFIRMATIONS = 2
GUIDANCE_HOLD_MS = 5_000
OBSTACLE_RECHECK_HOLD_MS = 1_500
OBSTACLE_ALERT_REPEAT_MS = 5_000
OBSTACLE_DEADLINE_MS = 7_000
SAFE_FRAMES_TO_RESUME = 2
CARDINAL = {"left", "right", "forward"}


class Arbitrator:
    """四规则仲裁器的可执行参考实现（用于消融实验与 App 端一致性验证）。"""

    def __init__(self, rules=("confirm", "conflict", "hold", "timeout")):
        self.rules = set(rules)
        self.last_announced = None
        self.candidate_dir = None
        self.candidate_streak = 0
        self.hold_until = 0.0
        self.safe_streak = 0
        self.conflict_state = None
        self.conflict_streak = 0
        self.last_alert_t = -1e9
        self.unknown_streak = 0
        # 统计
        self.stats = {"announcements": 0, "direction_changes": 0, "stops": 0, "obstacle_overrides": 0}

    def _announce(self, direction, t):
        if direction != self.last_announced:
            self.stats["direction_changes"] += 1
        self.last_announced = direction
        self.stats["announcements"] += 1

    def _stop(self, reason, t):
        if "hold" in self.rules:
            self.hold_until = t + GUIDANCE_HOLD_MS / 1000
        self.safe_streak = 0
        if t - self.last_alert_t >= OBSTACLE_ALERT_REPEAT_MS / 1000:
            self.last_alert_t = t
        self.stats["stops"] += 1
        self._announce_reason = reason

    def on_nav(self, direction, t):
        """导航通道结果到达。"""
        if "confirm" in self.rules:
            if direction == self.candidate_dir:
                self.candidate_streak += 1
            else:
                self.candidate_dir = direction
                self.candidate_streak = 1
            if self.candidate_streak < NAV_CONFIRMATIONS:
                return
        if t < self.hold_until:
            return
        self._announce(direction, t)

    def on_obstacle(self, direction, t, stairs=False, t_sent=None):
        """避障通道结果到达。t_sent 为请求发出时间，用于超时判定。"""
        if t_sent is not None and "timeout" in self.rules and (t - t_sent) * 1000 > OBSTACLE_DEADLINE_MS:
            self._stop("timeout", t)
            return
        if stairs:
            self._stop("stairs", t)
            return
        if direction in (None, "unknown", "none"):
            if "timeout" in self.rules:
                self.unknown_streak += 1
                if self.unknown_streak >= OBSTACLE_CONFIRMATIONS:
                    self._stop("unknown", t)
                    return
                self.hold_until = max(self.hold_until, t + OBSTACLE_RECHECK_HOLD_MS / 1000)
                return
        else:
            self.unknown_streak = 0
        # 冲突检测
        nav_dir = self.candidate_dir if self.candidate_streak >= NAV_CONFIRMATIONS else None
        if ("conflict" in self.rules and nav_dir in CARDINAL and direction in CARDINAL
                and nav_dir != direction):
            key = f"{nav_dir}_{direction}"
            if key == self.conflict_state:
                self.conflict_streak += 1
            else:
                self.conflict_state = key
                self.conflict_streak = 1
            if self.conflict_streak >= OBSTACLE_CONFIRMATIONS:
                self.stats["obstacle_overrides"] += 1
                if "hold" in self.rules:
                    self.hold_until = t + GUIDANCE_HOLD_MS / 1000
                self._announce(direction, t)
            else:
                if "hold" in self.rules:
                    self.hold_until = max(self.hold_until, t + OBSTACLE_RECHECK_HOLD_MS / 1000)
            return
        # 安全帧
        if direction in CARDINAL and (nav_dir is None or direction == nav_dir):
            self.safe_streak += 1
            if (self.safe_streak >= SAFE_FRAMES_TO_RESUME and self.hold_until
                    and t >= self.hold_until):
                self.hold_until = 0
        if direction in CARDINAL and t >= self.hold_until:
            # 非冲突、方向一致或导航尚未确认时，仅更新状态，不重复播报
            pass


def run_trace(trace, rules):
    arb = Arbitrator(rules)
    events = []
    nav = trace["nav"]
    obs = trace.get("obs") or [None] * len(nav)
    stairs = trace.get("stairs") or [False] * len(nav)
    t = trace.get("t") or [i * 0.7 for i in range(len(nav))]
    t_sent = trace.get("t_sent") or [None] * len(nav)
    for i in range(len(nav)):
        events.append(("nav", t[i], nav[i]))
        if obs[i] is not None or stairs[i]:
            events.append(("obs", t[i], obs[i], stairs[i], t_sent[i]))
    # 按 (时间, 类型) 排序，obs 后到覆盖 nav
    events.sort(key=lambda e: (e[1], 0 if e[0] == "nav" else 1))
    for e in events:
        if e[0] == "nav":
            arb.on_nav(e[2], e[1])
        else:
            arb.on_obstacle(e[2], e[1], stairs=e[3], t_sent=e[4])
    return arb.stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    trace = json.load(open(args.trace, encoding="utf-8"))

    configs = {
        "full": ("confirm", "conflict", "hold", "timeout"),
        "no_confirm": ("conflict", "hold", "timeout"),
        "no_conflict": ("confirm", "hold", "timeout"),
        "no_hold": ("confirm", "conflict", "timeout"),
        "no_timeout": ("confirm", "conflict", "hold"),
        "none": (),
    }
    result = {name: run_trace(trace, rules) for name, rules in configs.items()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        json.dump(result, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
