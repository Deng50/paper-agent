# Known Issues @ M5 P1 baseline

> 登记 M5 P1 启动期发现的、超出 P1 范围、不在本 milestone 处理的预存账单。
> 留待 M6（鲁棒 / 可观测）或后续 milestone 评估。

---

## Bill 1：Windows 本机 pytest native crash（starlette TestClient + anyio）

**症状**：
在 Windows 本机 `.venv` 跑 `pytest`（全套）时，`tests/test_m1.py::test_status_shape_with_auth`
触发 `Windows fatal exception: access violation`，pytest 进程异常退出 → 后续 14+ 个测试
连锁 `ERROR ... PermissionError: [WinError]`（tmpdir 句柄残留无法清理）→ 没有最终
`X passed, Y failed in Zs` 总结行。

**触发栈顶**：
```
File "D:\APP\anaconda3\Lib\threading.py", line 1167 in _wait_for_tstate_lock
File "D:\APP\anaconda3\Lib\threading.py", line 1147 in join
File "...\anyio\from_thread.py", line 556 in start_blocking_portal
File "...\starlette\testclient.py", line 418 in _portal_factory
File "...\httpx\_client.py", line 1014 in _send_single_request
File "D:\paper-agent\tests\test_m1.py", line 36 in test_status_shape_with_auth
```

**根因**：
starlette TestClient 用 anyio blocking_portal + httpx sync transport，在 Windows
threading 上 join 时偶发 native 段错误。已知上游问题，跨 anyio / starlette / httpx
三方协作链，非 paper-agent 自身代码缺陷。

**为何不在 M5 P1 处理**：
- M5 P1 范围 = 画像自更新前置 5 项整理，不涉及 Windows 兼容性
- 真正的 CI / dev baseline 在 Linux 环境（容器或 WSL），owner 跑 baseline 也在那里
- M4_to_M5 §2 末态「baseline 1 fail」即 Linux 环境数字
- Windows 本机仅用作 IDE / 改代码，不强求测试全套绿

**M5 P1 适配方案**（owner 确认）：
本机用「定向验证」= 改动相关文件 pytest + 全库 ruff / mypy。Windows native crash
作为预存账单留档，本 milestone 不修。

**后续处理候选**：
- M6 范畴：CI 改在 Linux runner 跑全套；本机 dev workflow 文档化「定向验证」
- 或：迁移到 WSL 跑全套测试
- 或：替换 starlette TestClient 为 `httpx.ASGITransport` + 异步 async client（绕开 blocking_portal）

---

## Bill 2：`tests/test_m3_mail.py:68` mypy `union-attr` 警告

**症状**：
```
tests\test_m3_mail.py:68: error: Item "None" of "_Call | None" has no attribute "args"  [union-attr]
```

**代码**（`test_send_email_calls_smtp` 内）：
```python
sent_msg = mock_send.await_args.args[0]
```

**根因**：
`AsyncMock.await_args` 静态类型是 `_Call | None`；测试逻辑保证此处已 `await_count == 1`
故运行时非 None，但 mypy 看不出来。

**为何不在 M5 P1 处理**：
- 预存于 M3 commit，与 M5 P1 ① 修复的另一个测试无关
- 不影响 `mypy src` 全库（src/ 通过），仅在显式 `mypy tests/test_m3_mail.py` 触发
- 项目质量门禁约定 `mypy src` 即可，tests/ 类型严格度本来就低

**后续处理候选**：
- 最小改动：`assert mock_send.await_args is not None` 在解构前一行加 narrow
- 或：用 `cast(Call, mock_send.await_args).args[0]`

---

> 更新规范：每条账单留触发 milestone（M5 P1）、症状、根因、不处理理由、后续候选。
> 修复时把对应条目从此文件移到 commit / handover changelog。
