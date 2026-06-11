"""§6.11 必验：newapi 网关是否透传 prompt caching（cache_control: ephemeral）。

协议（owner 2026-05-22）：
- 两发完全相同的请求，复用 scoring.py 的同一通道（base_url=newapi, 同模型）。
- 第 1 发若 cache_creation_input_tokens == 0 → 判定 newapi 不透传，不跑第 2 发。
- 第 1 发 cache_creation > 0 → 跑第 2 发，看 cache_read_input_tokens 是否 > 0。

注意：Haiku 类模型最小可缓存长度 2048 tokens，故 system 块做到 ~1.2 万 tokens，
排除「未达门槛」的假阴性。本脚本为一次性诊断，不是生产代码。

跑法：  python -m uv run python scripts/probe_cache.py
"""

from __future__ import annotations

import asyncio
import json

from anthropic import AsyncAnthropic

from lit_agent.core.config import get_settings

MODEL = "claude-haiku-4-5-20251001"

# 确定性填充：两发完全一致的静态前缀。每行 ~20 tokens × 700 行 ≈ 1.4 万 tokens，
# 远超 Haiku 的 2048 最小可缓存门槛。内容无任何指令。
_FILLER = "\n".join(
    f"Line {i:04d}: deterministic filler for the prompt-cache passthrough probe; "
    f"this text carries no instructions and must be ignored by the model."
    for i in range(700)
)


def _system_blocks() -> list[dict]:
    return [
        {
            "type": "text",
            "text": "You are a probe. Ignore the following filler entirely.\n\n" + _FILLER,
            "cache_control": {"type": "ephemeral"},
        }
    ]


async def _one_call(client: AsyncAnthropic, label: str) -> dict:
    resp = await client.messages.create(  # type: ignore[call-overload]
        model=MODEL,
        max_tokens=8,
        system=_system_blocks(),
        messages=[{"role": "user", "content": "Reply with the single word: OK"}],
    )
    usage = resp.usage.model_dump()
    print(f"\n===== {label} usage (完整对象) =====")
    print(json.dumps(usage, ensure_ascii=False, indent=2))
    return usage


async def main() -> None:
    s = get_settings()
    print(f"base_url = {s.anthropic_base_url or '(官方 api.anthropic.com)'}")
    print(f"model    = {MODEL}")
    client = AsyncAnthropic(
        api_key=s.anthropic_api_key,
        base_url=s.anthropic_base_url or None,
        timeout=60.0,
    )

    u1 = await _one_call(client, "CALL 1")
    cc = u1.get("cache_creation_input_tokens") or 0
    if cc == 0:
        print(
            "\n[判定] 第 1 发 cache_creation_input_tokens == 0 "
            "→ newapi 不透传 cache_control。按协议不跑第 2 发。"
        )
        return

    u2 = await _one_call(client, "CALL 2")
    cr = u2.get("cache_read_input_tokens") or 0
    print(
        f"\n[判定] 第 1 发 cache_creation={cc} > 0；"
        f"第 2 发 cache_read_input_tokens={cr} "
        f"→ {'透传成功 ✅' if cr > 0 else '写入了但第 2 发未命中读缓存 ⚠️'}"
    )


if __name__ == "__main__":
    asyncio.run(main())
