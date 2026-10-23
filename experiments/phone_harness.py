# -*- coding: utf-8 -*-
"""手机端实验控制：建立隧道、启动 App、抓取 trace。

用法：
    python phone_harness.py tunnel          # 建立 adb reverse 隧道
    python phone_harness.py status          # 查看设备与隧道
    python phone_harness.py launch          # 启动 App
    python phone_harness.py logcat [秒数]    # 抓取日志（默认 30 秒）
    python phone_harness.py screenshot      # 截图到 results/
    python phone_harness.py maps            # 列出手机上的地图与节点数

前提：adb 在 PATH，或设置 ADB 环境变量。
"""
import argparse
import os
import re
import subprocess
import sys
import time

ADB = os.environ.get("ADB", r"C:\Users\the\AppData\Local\Android\Sdk\platform-tools\adb.exe")
PKG = "com.wsplus.guide"
BASE = "/data/data/com.wsplus.guide/files/topology_maps"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def adb(*args, capture=True, timeout=60):
    cmd = [ADB] + list(args)
    r = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def cmd_tunnel():
    rc, out = adb("reverse", "tcp:8000", "tcp:8000")
    print(f"建立隧道 tcp:8000 -> tcp:8000: {'OK' if rc == 0 else 'FAIL'}")
    if out.strip():
        print(out.strip())
    rc, out = adb("reverse", "--list")
    print("当前隧道列表:")
    print(out.strip() or "  (空)")
    print("\n提示：手机 App 中云服务地址应填 http://127.0.0.1:8000")
    print("      手机需保持 USB 连接，断开后隧道失效需重跑本命令。")


def cmd_status():
    rc, out = adb("devices", "-l")
    print("=== 设备 ===")
    print(out.strip())
    rc, out = adb("shell", "getprop ro.product.model")
    print(f"型号: {out.strip()}")
    rc, out = adb("shell", "dumpsys package %s | grep -E 'versionName|lastUpdateTime'" % PKG)
    print("=== App 版本 ===")
    print(out.strip())
    rc, out = adb("reverse", "--list")
    print("=== 隧道 ===")
    print(out.strip() or "  (无)")
    # 云端连通性（从手机侧）
    rc, out = adb("shell", "curl -s --max-time 5 http://127.0.0.1:8000/health 2>/dev/null || echo NO_CURL")
    print("=== 手机访问云端 /health ===")
    print((out.strip()[:400] if out.strip() else "无响应"))


def cmd_launch():
    rc, out = adb("shell", "am force-stop %s" % PKG)
    time.sleep(1)
    rc, out = adb("shell", "am start -n %s/.MainActivity" % PKG)
    print("启动 App:", "OK" if rc == 0 else "FAIL")
    print(out.strip())


def cmd_logcat(seconds=30):
    print(f"抓取 logcat {seconds} 秒（仅本 App 相关）...")
    p = subprocess.Popen([ADB, "logcat", "-v", "time"], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines = []
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            line = p.stdout.readline()
            if not line:
                break
            if any(k in line for k in ("wsplus", "CloudApi", "Topology", "OkHttp", "AndroidRuntime")):
                lines.append(line.rstrip())
                print(line.rstrip())
    finally:
        p.terminate()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"logcat_{time.strftime('%Y%m%d_%H%M%S')}.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n已保存 {len(lines)} 行 -> {path}")


def cmd_screenshot():
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"screen_{time.strftime('%Y%m%d_%H%M%S')}.png")
    rc, out = adb("exec-out", "screencap", "-p")
    # 用二进制方式重取
    r = subprocess.run([ADB, "exec-out", "screencap", "-p"], capture_output=True)
    with open(path, "wb") as f:
        f.write(r.stdout)
    print(f"截图 -> {path} ({len(r.stdout)} bytes)")


def cmd_maps():
    rc, out = adb("shell", "run-as %s ls %s" % (PKG, BASE))
    dirs = [d.strip() for d in out.splitlines() if d.strip() and "Permission denied" not in d]
    print("=== 手机上的地图 ===")
    for d in dirs:
        rc2, out2 = adb("shell", "run-as %s ls '%s/%s'" % (PKG, BASE, d))
        n = len([x for x in out2.splitlines() if re.search(r"\.(jpg|jpeg|png)$", x, re.I)])
        flag = "✓" if n > 0 else "（空）"
        print(f"  {d:45s} {n:3d} 节点 {flag}")


def cmd_pull(map_name, dest=None):
    """导出指定地图到本地（二进制安全，经 cmd 重定向）。"""
    dest = dest or os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "phone_maps")
    os.makedirs(dest, exist_ok=True)
    tar_path = os.path.join(dest, f"{map_name}.tar")
    cmdline = f'"{ADB}" exec-out run-as {PKG} tar -cf - -C {BASE} {map_name} > "{tar_path}"'
    rc = subprocess.run(cmdline, shell=True).returncode
    size = os.path.getsize(tar_path) if os.path.exists(tar_path) else 0
    print(f"导出 {map_name}: {size} bytes -> {tar_path}")
    if size > 0:
        subprocess.run(["tar", "-xf", tar_path, "-C", dest], shell=False)
        print(f"解包到 {dest}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["tunnel", "status", "launch", "logcat", "screenshot", "maps", "pull"])
    ap.add_argument("value", nargs="?", default="")
    args = ap.parse_args()

    if not os.path.exists(ADB) and os.environ.get("ADB") is None:
        print(f"找不到 adb: {ADB}")
        print("请设置环境变量 ADB 指向 adb.exe")
        sys.exit(1)

    if args.action == "tunnel":
        cmd_tunnel()
    elif args.action == "status":
        cmd_status()
    elif args.action == "launch":
        cmd_launch()
    elif args.action == "logcat":
        cmd_logcat(int(args.value) if args.value else 30)
    elif args.action == "screenshot":
        cmd_screenshot()
    elif args.action == "maps":
        cmd_maps()
    elif args.action == "pull":
        if not args.value:
            print("用法: phone_harness.py pull <地图名>")
            sys.exit(1)
        cmd_pull(args.value)


if __name__ == "__main__":
    main()
