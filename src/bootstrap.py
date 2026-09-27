"""命令行入口的通用引导:路径、编码、日志、LangSmith。

课程对应:
    第03章 §2.3(p6)      LangSmith 的四个环境变量(必须在调用前设置)
    第02章 §5.5(p47)     失败处理:给出带指引的报错,而不是裸异常

为什么单独一个模块:
    旧版每个 CLI 文件都重复这四件事(把 src 塞进 sys.path、重配 stdin/stdout、
    配 logging、压掉 httpx 噪音),四个文件几乎逐行相同。
"""
import logging
import sys
from pathlib import Path

# 允许 `python src/xxx.py` 直接运行:把 src/ 与项目根都放进 sys.path
_SRC = Path(__file__).resolve().parent          # src/
_ROOT = _SRC.parent                             # 项目根
for p in (str(_SRC), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Windows 控制台默认 GBK,中文输入输出会乱码(run_*.cmd 里已 chcp 65001,
# 这里再做一层保险,保证直接从 PyCharm 运行时也正常)
try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 —— 某些环境 stdin 不可重配
    pass


def setup_logging(stream=None) -> None:
    """审计日志走 stderr,和聊天正文(stdout)不混流。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
        stream=stream or sys.stderr,
    )
    # 第08章 §5.4(p99-111)的审计 Hook 会打很多行,压掉底层请求噪音
    for noisy in ("httpx", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def setup_langsmith() -> None:
    """补齐 LangSmith 四个环境变量(第03章 §2.3 p6)。"""
    from agent.runtime import setup_langsmith as _setup

    _setup()
