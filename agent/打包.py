# -*- coding: utf-8 -*-
r"""
打包工具 —— 一条命令生成三种「一个文件」的交付物
================================================

用法：
    python 打包.py py      # 生成  dist/单文件版_客服程序.py
    python 打包.py exe     # 生成  dist/拼多多智能客服.exe
    python 打包.py zip     # 生成  dist/拼多多智能客服_完整包.zip      （含全部素材，约 40 MB）
    python 打包.py lite    # 生成  dist/拼多多智能客服_邮件版.zip      （去掉大图，可作邮件附件）
    python 打包.py all     # 以上全做

为什么能「干净拼接」成一个 .py
------------------------------
经 AST 分析，本项目 5 个模块之间**没有任何真实的重名函数/类**（那些"重名"
其实都是 auto_keeper 里的 `from xxx import ...` 语句）。
所以按依赖顺序把源码拼在一个文件里即可，配合 `sys.modules` 别名，
原来那些 `from pdd_send import ...` 仍然能正常命中。

顺序（依赖在前）：
    asset_path -> sensitive -> 款式识别 -> pdd_send -> auto_keeper

注意事项（已在生成器里自动处理）：
  1. 每个模块的 `if __name__ == "__main__":` 会被改成 `if False:`，
     否则直接运行合并文件时它们会**全部执行**。
  2. 每个模块代码之后插一段 `sys.modules` 别名注册，
     让后续模块的 `import xxx` / `from xxx import yyy` 仍能命中。
  3. 末尾由本工具写入统一入口：
       带子命令（goto/consult/chosen/text/...）→ 走 pdd_send 的 CLI
       带 --selftest / 自检            → 就地自检（不碰浏览器，离线可跑）
       不带子命令（或 --interval 等）   → 走 auto_keeper 守护进程

EXE（PyInstaller onefile）如何定位配置与素材
--------------------------------------------
  · kb.json  —— 优先 exe 同目录（用户可改），其次 exe 内自带（--add-data 塞进去的）
  · 素材     —— 优先 exe 同目录的 素材\（用户可增删），其次 exe 内自带的
  见 asset_path.py 的 app_dir()/bundle_dir()/kb_path()/material_roots()。
"""
import ast
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, "dist")
BUILD = os.path.join(BASE, "build")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 依赖顺序：被依赖的在前
MODULES = ["asset_path", "sensitive", "款式识别", "pdd_send", "auto_keeper"]
ENTRY_MODULE = "auto_keeper"        # 提供守护进程 main()

# 运行时必需、要打进 zip 的代码/配置文件
CODE_FILES = ["asset_path.py", "sensitive.py", "款式识别.py", "pdd_send.py",
              "auto_keeper.py", "agent_start_keeper.py", "kb.json", "config.json",
              "打包.py", "测试意图判断.py"]
DOC_FILES = ["全自动客服使用说明.md", "命令说明.md"]
# 素材：只带「程序运行时真正要读的本地图片」
# （视频都在拼多多工作台素材库里，属于云端，不需要拷）
ASSET_SUBDIRS = [
    os.path.join("实拍图", "A B混合"),
    os.path.join("实拍图", "A款实拍图"),
    os.path.join("实拍图", "B款实拍图"),
    os.path.join("实拍图", "定风翼堵盖"),
    os.path.join("实拍图", "黑旗600脚踏挡杆实拍"),
]
# 「邮件版」：去掉体积最大的 A款实拍图（约 15 MB，属"客户主动要图"场景，
# 用户说平时不发图），其余分类开场图全部保留，整包压到 25 MB 以内便于普通邮箱附件。
ASSET_SUBDIRS_LITE = [p for p in ASSET_SUBDIRS if "A款实拍图" not in p]

SINGLE_NAME = "单文件版_客服程序.py"
EXE_NAME = "拼多多智能客服.exe"
ZIP_NAME = "拼多多智能客服_完整包.zip"
ZIP_NAME_LITE = "拼多多智能客服_邮件版.zip"
ZIP_TOP = "拼多多智能客服"
LAUNCHER = "启动客服.bat"
READ_ME = "收件人必读.md"


# ---------------------------------------------------------------- 工具

def read(name):
    return io.open(os.path.join(BASE, name), encoding="utf-8").read()


def neutralize_main(src):
    """把 `if __name__ == "__main__":` 改成 `if False:`，避免合并后被执行。"""
    return re.sub(r'^if\s+__name__\s*==\s*[\'"]__main__[\'"]\s*:',
                  'if False:  # 【单文件版】原模块入口，不单独执行',
                  src, flags=re.M)


def alias_block(names):
    return (
        "\n# ======== 模块别名（单文件版专用）: 让后续 import 语句命中本命名空间 ========\n"
        "for _alias in %r:\n"
        "    sys.modules.setdefault(_alias, sys.modules[__name__])\n" % (tuple(names),)
    )


def collect_commands():
    """从 pdd_send._main() 里抓出所有子命令名，写成入口分派用。"""
    src = read("pdd_send.py")
    cmds = set(re.findall(r'cmd\s*==\s*"([^"]+)"', src))
    return sorted(cmds)


def _hr(title=""):
    print("\n" + "=" * 70)
    if title:
        print("  " + title)
        print("=" * 70)


# ---------------------------------------------------------------- 生成单文件 py

SELFTEST_BLOCK = '''

# ======== 离线自检（不连接浏览器，收件人也能跑） ========
def _selftest():
    """打印程序关键路径与配置状态，用于排查『为什么收不到/发不出』。"""
    import asset_path as _ap
    print("=" * 62)
    print("  拼多多智能客服 · 自检")
    print("=" * 62)
    print("  程序目录    :", _ap.app_dir())
    print("  包内自带目录 :", _ap.bundle_dir())
    _kp = _ap.kb_path()
    print("  kb.json     :", _kp, "✅" if os.path.exists(_kp) else "❌ 缺失（将用代码内置默认值）")
    try:
        _n = len(load_kb_rules())
    except Exception as _e:
        _n = "读取失败：%s" % _e
    print("  知识库规则   :", _n, "条")
    print("  素材查找根目录:")
    for _r in _ap.material_roots():
        print("      %s  %s" % (_r, "✅" if os.path.isdir(_r) else "（不存在）"))
    print("  素材目录检查 :")
    _root = str(_ap.config().get("客服资料根目录") or "").replace("/", os.sep)
    for _sub in (("实拍图", "A B混合"), ("实拍图", "A款实拍图"),
                 ("实拍图", "B款实拍图"), ("实拍图", "定风翼堵盖"),
                 ("实拍图", "黑旗600脚踏挡杆实拍")):
        _d = _ap.resolve(os.path.join(_root, *_sub))
        print("      %-26s %s" % ("/".join(_sub), "✅ " + _d if os.path.isdir(_d) else "⚠️ 本机没有，将跳过"))
    try:
        import websocket as _ws
        print("  websocket   : ✅", getattr(_ws, "__version__", ""))
    except Exception as _e:
        print("  websocket   : ❌", _e, "（请 pip install websocket-client）")
    print("=" * 62)
    print("  提示：如提示『无可见会话』，把工作台左侧切到【今日接待】即可。")
    print("=" * 62)
'''


def build_single_py():
    os.makedirs(DIST, exist_ok=True)
    out = []
    usage = [
        "python {f}                  # 启动全自动客服守护进程（每 30 秒巡检）",
        "python {f} --interval 30    # 同上，指定巡检间隔",
        "python {f} --once           # 只巡检一轮就退出（排查用）",
        "python {f} --once --dry     # 预演：只判断不发送（排查用）",
        "python {f} --selftest       # 离线自检：打印路径/配置/素材状态",
        "python {f} goto             # 打开/激活拼多多客服工作台",
        "python {f} consult          # 按当前会话商品发开场素材",
        "python {f} chosen A         # 发 A 款实拍视频",
        "python {f} videos           # 列出工作台素材库视频标题",
    ]
    out.append(
        "# -*- coding: utf-8 -*-\n"
        '"""\n'
        "拼多多智能客服 —— 单文件版（自动生成，请勿手改）\n"
        "================================================================\n"
        "由 `打包.py py` 生成，把 %d 个模块按依赖顺序拼成一个文件：\n"
        "    %s\n\n"
        "用法：\n%s\n\n"
        "依赖：Python 3.8+ 与 websocket-client（pip install websocket-client）\n"
        "配置文件 kb.json 与素材目录需与本文件同级（也可以直接跑 exe 版）。\n"
        '"""\n'
        "import os\n"
        "import sys\n"
        "\n"
        "# ---- 控制台编码兜底：Windows 默认 GBK，直接双击 exe 时中文/符号会崩 ----\n"
        "if getattr(sys, \"frozen\", False):\n"
        "    try:\n"
        "        import ctypes\n"
        "        ctypes.windll.kernel32.SetConsoleOutputCP(65001)\n"
        "        ctypes.windll.kernel32.SetConsoleCP(65001)\n"
        "    except Exception:\n"
        "        pass\n"
        "for _s in (sys.stdout, sys.stderr):\n"
        "    try:\n"
        "        _s.reconfigure(encoding=\"utf-8\", errors=\"replace\")\n"
        "    except Exception:\n"
        "        pass\n"
        "\n"
        % (len(MODULES), " -> ".join(MODULES),
           "\n".join("    " + u.format(f=SINGLE_NAME) for u in usage))
    )

    for name in MODULES:
        src = read(name + ".py")
        out.append("\n\n# " + "=" * 74 + "\n")
        out.append("# ↓↓↓↓↓↓  模块：%s.py  ↓↓↓↓↓↓\n" % name)
        out.append("# " + "=" * 74 + "\n")
        out.append(neutralize_main(src))
        out.append(alias_block([name]))

    cmds = collect_commands()
    out.append(SELFTEST_BLOCK)
    out.append(
        "\n\n# " + "=" * 74 + "\n"
        "# 统一入口（由 打包.py 生成）\n"
        "# " + "=" * 74 + "\n"
        "_CLI_COMMANDS = %r\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    # 离线自检\n"
        "    if len(sys.argv) > 1 and sys.argv[1] in (\"--selftest\", \"selftest\", \"自检\"):\n"
        "        _selftest()\n"
        "        sys.exit(0)\n"
        "    # 带子命令（goto / consult / chosen / text …）→ 走 pdd_send 的命令行\n"
        "    if len(sys.argv) > 1 and sys.argv[1] in _CLI_COMMANDS:\n"
        "        try:\n"
        "            _main()\n"
        "        except (RuntimeError, IndexError) as e:\n"
        "            print(\"❌ \" + str(e))\n"
        "            sys.exit(1)\n"
        "    else:\n"
        "        # 不带子命令 → 启动全自动客服守护进程\n"
        "        try:\n"
        "            main()\n"
        "        except KeyboardInterrupt:\n"
        "            print(\"\\n已停止。\")\n"
        % (cmds,)
    )

    text = "".join(out)
    dst = os.path.join(DIST, SINGLE_NAME)
    io.open(dst, "w", encoding="utf-8", newline="\n").write(text)
    print("[+] 单文件版已生成：%s" % dst)
    print("    行数 %d｜体积 %.1f KB｜CLI 子命令 %d 个"
          % (len(text.splitlines()), len(text.encode("utf-8")) / 1024.0, len(cmds)))
    return dst


# ---------------------------------------------------------------- 生成 EXE

def _customer_root():
    """从 kb.json 的 _路径配置 读『客服资料根目录』。"""
    try:
        import asset_path
        return str(asset_path.config().get("客服资料根目录") or "").replace("/", os.sep)
    except Exception:
        return r"D:\work\客服资料"


def build_exe():
    py = build_single_py()          # exe 直接以单文件版为入口
    try:
        import PyInstaller                                    # noqa: F401
    except ImportError:
        print("❌ 未安装 PyInstaller，请先执行：pip install pyinstaller")
        return None
    os.makedirs(DIST, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)

    root = _customer_root()
    mix = os.path.join(root, "实拍图", "A B混合") if root else ""
    sep = os.pathsep                                        # Windows = ';'

    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean", "--onefile", "--console",
           "--name", os.path.splitext(EXE_NAME)[0],
           "--distpath", DIST,
           "--workpath", BUILD,
           "--specpath", BUILD,
           "--hidden-import", "websocket",
           "--exclude-module", "tkinter",
           "--add-data", "%s%s." % (os.path.join(BASE, "kb.json"), sep)]
    if mix and os.path.isdir(mix):
        cmd += ["--add-data", "%s%s%s" % (mix, sep, os.path.join("素材", "实拍图", "A B混合"))]
        print("[i] 内置 A B混合 对比图（%s）" % mix)
    else:
        print("[!] 未找到 A B混合 目录，exe 将不含内置对比图（会改用程序目录下 素材/ 里的）")
    cmd.append(py)

    _hr("开始打包 EXE（PyInstaller onefile，首次约 1-3 分钟）")
    print("    " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    r = subprocess.run(cmd, cwd=BASE)
    exe = os.path.join(DIST, EXE_NAME)
    if r.returncode != 0 or not os.path.exists(exe):
        print("❌ EXE 打包失败（返回码 %s）" % r.returncode)
        return None
    print("[+] EXE 已生成：%s（%.1f MB）" % (exe, os.path.getsize(exe) / 1048576.0))
    return exe


# ---------------------------------------------------------------- 生成 ZIP

def _zip_tree(zf, src, arc):
    """把目录 src 递归写进 zip 的 arc 下。"""
    for r, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            p = os.path.join(r, fn)
            rel = os.path.relpath(p, src)
            zf.write(p, os.path.join(arc, rel))


LAUNCHER_TEXT = """@echo off
chcp 65001 >nul
title PDD Auto Customer Service
cd /d "%~dp0"

echo ============================================================
echo   PD D Auto Customer Service
echo ============================================================
echo.

rem 1) 优先用打包好的 exe（免装 Python）
if exist "拼多多智能客服.exe" (
    echo [启动] 拼多多智能客服.exe
    echo.
    "拼多多智能客服.exe" --interval 30
    goto end
)

rem 2) 没有 exe 就用 Python 跑单文件版（需先装 Python 与 websocket-client）
where python >nul 2>nul
if %errorlevel%==0 (
    echo [启动] 单文件版_客服程序.py （python）
    echo.
    python "单文件版_客服程序.py" --interval 30
    goto end
)

echo [错误] 既没有 拼多多智能客服.exe，也找不到 Python。
echo         请安装 Python 3 后执行：pip install websocket-client
echo.

:end
echo.
echo ============================================================
echo   Service stopped.
echo ============================================================
pause
"""


def build_zip(exe=None, lite=False):
    os.makedirs(DIST, exist_ok=True)
    zpath = os.path.join(DIST, ZIP_NAME_LITE if lite else ZIP_NAME)
    if exe is None:
        cand = os.path.join(DIST, EXE_NAME)
        exe = cand if os.path.exists(cand) else None
    subs = ASSET_SUBDIRS_LITE if lite else ASSET_SUBDIRS

    root = _customer_root()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # ① 程序本体
        if exe:
            zf.write(exe, os.path.join(ZIP_TOP, EXE_NAME))
        single = os.path.join(DIST, SINGLE_NAME)
        if not os.path.exists(single):
            single = build_single_py()
        zf.write(single, os.path.join(ZIP_TOP, SINGLE_NAME))

        # ② 配置（放根目录，收件人直接改） + 源码（放 源码/ 子目录）
        for fn in ("kb.json", "config.json"):
            p = os.path.join(BASE, fn)
            if os.path.exists(p):
                zf.write(p, os.path.join(ZIP_TOP, fn))
        for fn in CODE_FILES:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(BASE, fn)
            if os.path.exists(p):
                zf.write(p, os.path.join(ZIP_TOP, "源码", fn))

        # ③ 文档
        for fn in DOC_FILES:
            p = os.path.join(BASE, fn)
            if os.path.exists(p):
                zf.write(p, os.path.join(ZIP_TOP, fn))
        zf.writestr(os.path.join(ZIP_TOP, READ_ME), _readme_text())
        zf.writestr(os.path.join(ZIP_TOP, LAUNCHER), LAUNCHER_TEXT)
        zf.writestr(os.path.join(ZIP_TOP, "logs", "说明.txt"),
                    "本目录存放运行日志：auto_YYYY-MM-DD.log（每日一个）。\n"
                    "排查看最后几行即可。\n")

        # ④ 素材（本地真正要读的图片）
        for sub in subs:
            src = os.path.join(root, sub)
            if os.path.isdir(src):
                n0 = sum(len(f) for _, _, f in os.walk(src))
                if n0 == 0:
                    print("[i] 跳过空目录：%s" % sub)
                    continue
                _zip_tree(zf, src, os.path.join(ZIP_TOP, "素材", sub))
                print("[i] 已加入素材：%s（%d 个文件）" % (sub, n0))
            else:
                print("[!] 素材目录不存在，跳过：%s" % src)

    print("[+] ZIP 已生成：%s（%.1f MB）" % (zpath, os.path.getsize(zpath) / 1048576.0))
    return zpath


def _readme_text():
    root = _customer_root() or r"D:\work\客服资料"
    return u"""# 收件人必读 —— 拼多多智能客服（一键接管回复）

## 这是什么
一个**在你自己的电脑上运行**的拼多多客服助手：通过调试端口接管你已经登录的
拼多多商家后台，自动识别客户意图、按知识库回复、发实拍视频/图片。
它**不登录你的账号**，也**不上传你的数据**，只是帮你点鼠标、发消息。

## 三步跑起来
1. **装 Python（只有用 .py 版才需要；用 .exe 版可跳过）**
   到 python.org 下载 Python 3，安装时勾选「Add Python to PATH」，
   然后开一个命令行执行：`pip install websocket-client`
2. **打开带调试端口的浏览器并登录拼多多商家后台**
   双击包里的 `start_chrome_debug.bat`（若没有，见下方「手动开调试端口」），
   在弹出的窗口里登录你自己的拼多多商家账号，进入客服工作台。
3. **启动本程序**
   双击 `%s`（会自动优先用 exe），窗口里看到「巡检：…」就是在跑了。
   跑起来后**不要关这个窗口**，也不要关浏览器。

## 先做个自检（强烈建议）
   拼多多智能客服.exe --selftest
   （或 `python 单文件版_客服程序.py --selftest`）
会打印 kb.json 位置、知识库条数、素材目录是否存在。任何一项 ❌ 都要先修掉。

## 目录说明
| 文件/目录 | 作用 |
|---|---|
| `拼多多智能客服.exe` | 主程序（免装 Python，双击即用） |
| `单文件版_客服程序.py` | 同上，需要 Python（源码合并版，可读可改） |
| `kb.json` | **所有话术与规则**都在这里改（价格、发货、教程、视频映射…） |
| `源码/` | 原始分模块源码，方便二次开发 |
| `素材/实拍图/` | 程序要发的本地图片（视频在拼多多素材库里，不用拷） |
| `logs/` | 运行日志，出问题先看这里 |

> ⚠️ 若你拿到的是「邮件版」，`素材/实拍图/A款实拍图/` 可能为空（该目录图较大、为方便发邮件而省略）。
> 需要发 A 款实拍图时，把自己的照片拷进该目录即可，程序会自动扫描，无需改代码。

## 想改话术？
打开 `kb.json` 改对应字段（保持 JSON 格式正确），然后**重启程序**生效。
注释字段以 `_` 开头（`_说明` 等），可以留着不管。

## 常见问题
- **日志一直说「无可见会话」**：把客服工作台左侧从「全部会话」切到「**今日接待**」。
- **发不出视频**：先确认工作台素材库里确实有该标题的视频（程序只按标题找）。
- **提示没装 websocket**：命令行执行 `pip install websocket-client`。
- **exe 双击一闪而过**：说明启动报错，请改用命令行运行看报错信息。

## 手动开调试端口
关闭所有 Chrome/Edge，然后运行：
    chrome.exe --remote-debugging-port=9222 --user-data-dir="%%TEMP%%\\pdd_debug"
（Edge 把 chrome.exe 换成 msedge.exe）
再用这个窗口登录拼多多商家后台即可。

## 免责声明
本程序只是**本地自动化脚本**，所有回复内容与责任由使用者（店铺）承担。
请遵守平台规则，禁止发送诱导第三方（加微信/留电话/联系主店等）内容。
""" % LAUNCHER


# ---------------------------------------------------------------- main

def main():
    what = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    exe = None
    if what in ("exe", "all", "zip"):
        if what in ("exe", "all"):
            exe = build_exe()
    if what in ("py", "all"):
        build_single_py()
    if what in ("zip", "all"):
        build_zip(exe)
    if what in ("lite", "all"):
        build_zip(exe, lite=True)
    _hr("完成")
    for f in (SINGLE_NAME, EXE_NAME, ZIP_NAME, ZIP_NAME_LITE):
        p = os.path.join(DIST, f)
        print("  %-34s %s" % (f, ("%.2f MB" % (os.path.getsize(p) / 1048576.0))
                              if os.path.exists(p) else "（未生成）"))


if __name__ == "__main__":
    main()
