# logger.py
"""统一日志模块。

提供 get_logger(name) 工厂函数，所有模块共用同一套配置。
日志级别和格式可通过 config.yaml 的 logging 节配置。
"""

import logging
import sys

# 默认格式：时间 | 级别 | 模块名 | 消息
_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def setup_logging(config: dict | None = None):
    """根据配置字典初始化根 logger（仅执行一次）。

    config.yaml 示例：
        logging:
          level: DEBUG
          format: "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
          file: "agent.log"        # 可选，同时写文件
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    log_cfg = (config or {}).get("logging", {})
    level_name = log_cfg.get("level", "INFO").upper()
    fmt = log_cfg.get("format", _DEFAULT_FORMAT)
    datefmt = log_cfg.get("date_format", _DEFAULT_DATE_FORMAT)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    root = logging.getLogger("bu")
    root.setLevel(getattr(logging, level_name, logging.INFO))
    root.addHandler(handler)

    # 可选：同时写文件
    log_file = log_cfg.get("file")
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        root.addHandler(fh)

    # 第三方库保持 WARNING，减少噪音
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取子 logger，自动挂载到 bu 命名空间。

    用法：
        from logger import get_logger
        log = get_logger("server")
        log.info("Server started")
    """
    if not name.startswith("bu."):
        name = f"bu.{name}"
    return logging.getLogger(name)
