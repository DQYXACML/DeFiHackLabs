#!/usr/bin/env python3
"""检测 ``foundry.toml`` 中 RPC 端点是否开放 debug/trace 接口。

脚本使用纯标准库实现，不依赖 web3。它会读取项目根目录（或指定路径）
的 ``foundry.toml``，遍历 ``[rpc_endpoints]`` 下的所有端点，为每个端点发
送一组 JSON-RPC 请求，观察返回结构以判断接口是否可用。

用法示例::

    python src/test/check_rpc_debug_support.py
    python src/test/check_rpc_debug_support.py --methods debug_traceTransaction,trace_block
    python src/test/check_rpc_debug_support.py --json

说明：

* 对于返回 ``result`` 的请求直接判定为“支持”。
* 若返回 ``error``，只要不是 ``method not found``（code -32601），通常表明
  节点已开放接口，但需要合适参数，此时视为“支持（需正确参数）”。
* Public RPC 经常关闭调试接口，提示 ``method not found`` 属正常现象。
* WebSocket 端点需要安装 ``websocket-client`` 才能测试（若缺失会给出提示）。
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import toml
except ImportError as exc:  # pragma: no cover - 环境缺失直接退出
    print("错误：缺少 toml 库，请运行 pip install toml", file=sys.stderr)
    raise SystemExit(1) from exc

try:
    import websocket  # type: ignore
except ImportError:  # pragma: no cover - 可选依赖
    websocket = None  # type: ignore


DEFAULT_METHODS = (
    "debug_traceTransaction",
    "debug_traceBlockByNumber",
    "debug_traceCall",
    "trace_block",
    "trace_call",
)

EMPTY_TX = "0x" + "0" * 64
ZERO_ADDR = "0x" + "0" * 40


@dataclass
class MethodProbe:
    name: str
    params: List[Any]


def build_probes(methods: Iterable[str]) -> List[MethodProbe]:
    probes: List[MethodProbe] = []

    for method in methods:
        m = method.strip()
        if not m:
            continue

        if m == "debug_traceTransaction":
            probes.append(MethodProbe(m, [EMPTY_TX, {"tracer": "prestateTracer"}]))
        elif m == "debug_traceBlockByNumber":
            probes.append(MethodProbe(m, ["0x0", {}]))
        elif m == "debug_traceCall":
            call_obj = {"to": ZERO_ADDR, "data": "0x"}
            probes.append(MethodProbe(m, [call_obj, "latest", {"tracer": "callTracer"}]))
        elif m == "trace_block":
            probes.append(MethodProbe(m, ["0x0"]))
        elif m == "trace_call":
            call_obj = {"to": ZERO_ADDR, "data": "0x"}
            probes.append(MethodProbe(m, [call_obj, ["trace"], "latest"]))
        else:
            probes.append(MethodProbe(m, []))

    return probes


def load_rpc_endpoints(foundry_path: Path) -> Dict[str, str]:
    if not foundry_path.exists():
        raise FileNotFoundError(f"未找到 foundry.toml ({foundry_path})")

    with foundry_path.open("r", encoding="utf-8") as fh:
        data = toml.load(fh)

    endpoints = data.get("rpc_endpoints")
    if not isinstance(endpoints, dict):
        raise ValueError("foundry.toml 中缺少 [rpc_endpoints] 配置")

    return {k: str(v) for k, v in endpoints.items()}


def http_post(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def ws_post(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    if websocket is None:
        raise RuntimeError("未安装 websocket-client，无法测试 WebSocket 端点")

    ws = websocket.create_connection(url, timeout=timeout)
    try:
        ws.send(json.dumps(payload))
        data = ws.recv()
    finally:
        ws.close()

    return json.loads(data)


def send_request(url: str, method: str, params: List[Any], timeout: int, counter: int) -> Dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": counter,
        "method": method,
        "params": params,
    }

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme.startswith("ws"):
        return ws_post(url, payload, timeout)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"不支持的协议: {parsed.scheme or '<empty>'}")

    return http_post(url, payload, timeout)


def analyze_response(response: Dict[str, Any]) -> Tuple[bool, str]:
    if "result" in response:
        return True, "返回 result"

    error = response.get("error")
    if not error:
        return False, "未知响应"

    message = str(error.get("message", ""))
    code = error.get("code")

    if code == -32601 or "method not found" in message.lower():
        return False, "method not found"

    if "unsupported" in message.lower():
        return False, message

    if "not found" in message.lower():
        return True, message or "not found"

    return True, message or "error"


def probe_endpoint(name: str, url: str, probes: List[MethodProbe], timeout: int) -> List[Tuple[str, bool, str]]:
    results: List[Tuple[str, bool, str]] = []

    # 先做一个轻量调用验证端点可用
    try:
        send_request(url, "eth_chainId", [], timeout, 0)
    except Exception as exc:
        raise ConnectionError(f"连接失败: {exc}") from exc

    for idx, probe in enumerate(probes, start=1):
        try:
            raw = send_request(url, probe.name, probe.params, timeout, idx)
            supported, detail = analyze_response(raw)
        except Exception as exc:
            supported, detail = False, f"异常: {exc}"

        results.append((probe.name, supported, detail))

    return results


def format_results(name: str, url: str, results: List[Tuple[str, bool, str]]) -> str:
    lines = [f"[{name}] {url}"]
    for method, supported, detail in results:
        status = "支持" if supported else "不支持"
        lines.append(f"  - {method:>24}: {status} ({detail})")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检测 foundry.toml 中 RPC 是否开放调试 / Trace 接口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            说明：
              * 使用 --methods 以逗号分隔自定义检测列表。
              * 若需机器可读输出，添加 --json。
              * WebSocket 端点需要额外安装 websocket-client。
            """
        ),
    )

    parser.add_argument(
        "--foundry",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "foundry.toml",
        help="foundry.toml 路径（默认：项目根目录）",
    )

    parser.add_argument(
        "--methods",
        type=str,
        default=",".join(DEFAULT_METHODS),
        help="需要检测的方法列表，使用逗号分隔",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="请求超时时间（秒），默认 20",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出结果",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        endpoints = load_rpc_endpoints(args.foundry)
    except Exception as exc:
        print(f"加载 RPC 配置失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    probes = build_probes(args.methods.split(","))
    if not probes:
        print("未指定任何需要检测的方法", file=sys.stderr)
        raise SystemExit(1)

    all_results: Dict[str, Any] = {}

    for name, url in endpoints.items():
        try:
            results = probe_endpoint(name, url, probes, args.timeout)
        except Exception as exc:
            if args.json:
                all_results[name] = {"url": url, "error": str(exc)}
            else:
                print(f"[{name}] {url}")
                print(f"  - 检测失败: {exc}")
                print()
            continue

        if args.json:
            all_results[name] = {
                "url": url,
                "methods": [
                    {"method": m, "supported": s, "detail": d} for m, s, d in results
                ],
            }
        else:
            print(format_results(name, url, results))
            print()

    if args.json:
        print(json.dumps(all_results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
