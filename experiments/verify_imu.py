# -*- coding: utf-8 -*-
"""在手机上触发一次录制，验证 IMU 数据是否正确写入。

不依赖相机（可无相机权限），直接调用 App 的录制页会启动 IMU。
但更可靠的方式：用 adb 启动 App，手动进入录制页，这里只做数据检查。

用法：
    python verify_imu.py --wait 30
"""
import argparse
import os
import subprocess
import sys
import time

ADB = os.environ.get("ADB", r"C:\Users\the\AppData\Local\Android\Sdk\platform-tools\adb.exe")
PKG = "com.wsplus.guide"
MAPS = "/data/data/com.wsplus.guide/files/topology_maps"


def sh(cmd, timeout=60):
    r = subprocess.run([ADB, "shell", cmd], capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace")
    return r.stdout + r.stderr


def list_imu_files():
    out = sh(f"run-as {PKG} find {MAPS} -name imu.csv 2>/dev/null")
    return [l.strip() for l in out.splitlines() if l.strip() and "Permission" not in l]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=0, help="等待录制完成的秒数")
    args = ap.parse_args()

    print("=== 检查已存在的 imu.csv ===")
    files = list_imu_files()
    if not files:
        print("  暂未发现 imu.csv（需要先在 App 里录制一次地图）")
    for f in files:
        print(f"\n--- {f} ---")
        head = sh(f"run-as {PKG} head -3 '{f}'")
        print(head.strip())
        cnt = sh(f"run-as {PKG} wc -l '{f}'").strip()
        print(f"  行数: {cnt}")

    if args.wait > 0:
        print(f"\n等待 {args.wait} 秒后再次检查...")
        time.sleep(args.wait)
        files = list_imu_files()
        print(f"现在有 {len(files)} 个 imu.csv")
        for f in files:
            cnt = sh(f"run-as {PKG} wc -l '{f}'").strip()
            print(f"  {f}: {cnt}")


if __name__ == "__main__":
    main()
