# BaiduNetdisk 8.7.0 的原生模块：一个把全局键盘钩子写成顶层依赖的出货客户端

日期：2026-11-10
证据根：`~/rea-work-20261108/work/natives/`（提取清单 `native_binaries.json`、magic 普查 `baidunetdisk_all_natives.json`、全二进制 `rea_analyze_*.json`、函数级 `functions/*.json` + `functions_index.json`）
完整证据卡：`~/rea-work-20261108/reports/2026-11-11-native-binary-analysis.md`

## 为什么这个案例值得单独记

本研究线审计的 7 个已装 Electron 客户端里，**6 个是纯 JavaScript**（WorkBuddy / Qoder / Qoder-CN / OpenCode / GrokBot / Obsidian 原生模块数均为 0），Freebuff 的 4 个原生二进制全是打包的 ripgrep（无自研逻辑）。**只有百度网盘 8.7.0 带自研与第三方 N-API 插件**——即唯一的「JS 源码层拿不到行为」的样本。

`app.asar`（242,015,293 B / 37,271 文件）内 11 个 ELF、`app.asar.unpacked/` 另 6 个；`core.asar`（483 文件）与 `video_player.asar`（91 文件）各 0 个。按唯一哈希计 11 个，其中**运行时插件 4 个**：

| 模块 | 大小 | SHA-256 前缀 | 性质 |
|---|---|---|---|
| `uiohook-napi/build/Release/uiohook_napi.node` | 62,664 | `77ea9366c9da10d4` | 全局键盘/鼠标事件钩子 |
| `koffi/build/koffi/linux_x64/koffi.node` | 5,944,784 | `89023ea4dc3e8fd2` | Node.js FFI（可调用任意 C ABI） |
| `@baidu/pc-electron-native-util` | 89,744 | `4808b2223cfc3418` | 百度自研：自然排序 / 按 key 排序 |
| `@baidu/electron-panel-window` | 14,040 | `d2cbd3ba265eb10e` | 百度自研：X11 窗口激活 |

其余 4 个是 CMake 构建探测物（`CMakeDetermineCompilerABI_C/CXX.bin`、`CompilerIdC/CXX/a.out`，ELF **EXEC** 而非 DYN），6 个是 Linux 上的空桩（`macos-notification-state` / `windows-notification-state` / `windows-quiet-hours`，导出仅 `_init`/`_fini`）。

## 三条只有二进制层才能拿到的结论

### 1. 键盘钩子是**顶层直接依赖**，不是传递依赖

`app.asar` 内根 `package.json`（`{off:1961305, size:2742}`）的依赖块逐字：

```json
"auto-launch": "^5.0.6",
"uiohook-napi": "1.5.4",
"@baiducloud/sdk": "1.0.7",
"uuid": "10.0.0"
```

这否掉了一种常见辩解——「钩子是某个第三方包顺带拖进来的」。它是官方声明的直接依赖。全 asar 搜 `uiohook-napi` 只有 2 处命中（根 package.json + 该包自身 package.json），`node_modules/` 之外 0 命中，说明 JS 侧没有明文 `require('uiohook-napi')` 调用点（该包走 `node-gyp-build` 动态解析），因此**调用点只能从二进制与打包形态推，不能从 JS 源码读**。

### 2. 暴露给 JS 的事件字段全集（`uiohook_to_js_event` @ `0x103ed0`）

36 个基本块 / 456 行汇编，`ev_61a3ed35…`，callees = `napi_create_object` `napi_define_properties` `napi_create_uint32` `napi_create_int32` `napi_create_double` `napi_get_boolean` `napi_fatal_error`。**17 个 unique 字符串**里，属于 JS 事件字段的 10 个：

- 修饰键：`altKey` `ctrlKey` `metaKey` `shiftKey`
- 键盘：`keycode`
- 鼠标：`button` `clicks` `amount` `direction` `rotation`

即该模块把**整个显示服务器的**键鼠事件（含四修饰键状态与硬件 keycode）交给 JS 侧。源码层只能看到 `EventType` 枚举（4/5/6/7/8/9/11），拿不到字段全集。

### 3. 事件类型 10 被就地改写成 9（源码层不可见）

`dispatch_proc` @ `0x1039c0`（8 块 / 51 行，`ev_b7ec48af…`）：

```c
iVar6 = *param_1;
if (iVar6 == 10) { *(undefined4 *)__ptr = 9; }   /* 10 → 9 */
napi_call_threadsafe_function(lVar5, __ptr, 0);
```

上游 libuiohook 的「鼠标拖动」事件在进入 JS 前被改写成「鼠标移动」。JS 枚举里没有 10 正是这个原因——**这是 native 侧掩盖的语义合并，不是 JS 侧没实现**。

### 附：X11 强制激活窗口（`MakeKeyWindow` @ `0x1011b0`）

`XOpenDisplay` → `XSetInputFocus(..., RevertToParent=1, CurrentTime)` → `XInternAtom("_NET_ACTIVE_WINDOW")` → `XSendEvent(root, ..., 0x180000, &msg)`（format=32、source indication=**1**=应用发起）→ `XFlush`/`XCloseDisplay`。即绕过窗口管理器焦点策略把自身提到前台。同模块的 `MakePanel` / `MakeWindow` 无此行为。

## 边界（不得越过）

1. **反编译 ≠ 源码**。pseudocode 是 Ghidra 12.1.3 表示；结论只到「调了哪些 X11 / N-API 函数」，不到意图层。
2. **只在 X11 分支成立**。Windows 走 `SET_WINDOWS_HOOK_EX`、macOS 走 AXAPI，本次未分析对应二进制。
3. **没有动态观测**。没启动过客户端，没观测真实事件流。要说「实测到键盘事件外泄」还差一次 ptrace/strace 级观测；当前能写的是「依赖声明 + 导出符号 + `AddonStart` 存在」。
4. **`SortByKey` 已注册未导出**（`pc-electron-native-util/index.js` 只导 `BetterCompare`），`MakeAlwaysOnTop` 有符号无 JS 导出——「编译进去」不等于「运行时调用」。
5. REA 的 JavaScript application graph 把 uiohook 记成 `native-addon` 节点（`native_addon_bindings: 1`），但**不展开符号级调用图**；本卡结论全部来自 `analyze` / `function` 两条独立路径。

## 方法论附注（可迁移）

- `analyze` 成功时输出**裸 evidence 对象**（顶层直接有 `evidence_id`），`function` 才返回 `{ok,data}` 包裹——同一套 CLI 两种响应形态，解析器必须都吃。
- **同名函数必须传精确地址**：`uiohook_to_js_event` 有 `0x102ef0` 与 `0x103ed0` 两份，按名字调用返回 `invalid_value` 歧义错误并附着候选地址表。
- 逆向 provider 需要两个环境变量同时就位：`GHIDRA_INSTALL_DIR`（12.1.x）与 `JAVA_HOME`（**full JDK**，系统自带的是 runtime-only JRE 会被拒），缺任一返回 `provider_unavailable` / `not_configured`。
- ASAR 目录解析：`json_len` 在 offset 12，`base = 16 + json_len` 且**按 4 字节对齐**，用 `base + max(offset+size) == filesize` 自校验。

## 复算

```bash
cd ~/rea-work-20261108
export GHIDRA_INSTALL_DIR=$PWD/work/engines/ghidra-dist/ghidra_12.1.3_PUBLIC
export JAVA_HOME=$PWD/work/engines/jdk
python3 reports/extract_native_binaries.py && python3 reports/scan_all_natives.py
npx -y rea-agents@6.4.0 analyze work/natives/resources__node_modules__uiohook-napi__build__Release__uiohook_napi.node --format json > work/natives/rea_analyze_uiohook.json
bash reports/run_rea_native_functions.sh work/natives/resources__node_modules__uiohook-napi__build__Release__uiohook_napi.node AddonStart dispatch_proc 0x103ed0
```
