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

## 动态补测（2026-11-10 追加，含一次结论更正）

静态层的三处天花板在动态层补上了。完整证据卡在 `~/rea-work-20261108/reports/2026-11-11-uiohook-dynamic-observation.md`（288 行 / SHA-256 `d71ff76168edf2ce72cf87eed41dc81aa78808d59f26c8a507a95c0df4c809d1`，2026-11-12 有增补）。

**① 可加载性**：该 `.node` 是 N-API 模块（有 `napi_register_module_v1`），ABI 跨 Node 大版本稳定 → 系统 node 24.20.0 直接 `require()` 成功（`exports = ["start","stop","keyTap"]`），不必借 Electron 运行时。（顺带记：`ELECTRON_RUN_AS_NODE=1 /opt/baidunetdisk/baidunetdisk` 走不通——SUID sandbox FATAL / `GPU process isn't usable. Goodbye.`。）

**② 钩子收事件 + 「10→9」运行时成立**：XTEST 注入序列（`a` / Shift+`a` / motion / 按下→两段拖动→抬起）与捕获**逐条 1:1 对应共 11 条**；事件类型 `10` 计数 **0**，按下与抬起之间的两段拖动都报 **`9`**。这正面证实了 `dispatch_proc` 的 `if (iVar6 == 10) *(undefined4 *)__ptr = 9;`——**拖动被并入移动，JS 侧拿不到 type 10**。同时量到 X keycode → uiohook keycode 是**减 8**（38→30、50→42），修饰位 `shiftKey` 正确置位。

**③ keyTap 真的会投递——此前结论要撤回**：早先用 uiohook 自身的钩子（XRecord 后端）观察 `keyTap`，跨三次独立实验都是 0 事件，据此写了「keyTap 是 no-op」。**错在仪器**：`keyTap` 走 `XSendEvent`，而 XRecord 不记录合成事件。换成独立 X11 焦点接收端后，`keyTap(48,0)` 到手 `{type:2/3, send_event:1, keycode:56}`；复刻 `simulateCopy()` 的 Ctrl+C（`Ctrl=0x1d` Down → `C=0x2e` Tap → `Ctrl` Up）到手 4 条 `keycode 37/54/54/37`，第 2 条起 `state=4`（ControlMask）。
对照实验同 display 同时刻：钩子只 2 条（XTEST 的 `k=30`），焦点窗口 4 条（keyTap 的 `keycode=56 send_event=1` ×2 + XTEST 的 `keycode=38 send_event=0` ×2）。差别就在 `send_event`。
连带撤回一条反编译推断：「`helper_disp` 恒为 0 ⇒ `hook_post_event` 一进门就 return」——运行时非空（赋值在未反编译的函数里）。

**④ 谁在调它（`core.asar`，此前只扫了 `app.asar`）**：`require("uiohook-napi")`（off 78833954）、长按监听类（79312497）、`simulateCopy()` = 非 darwin 的 `keyTap(C,[Ctrl])`（79314940）、消费方 `.on("longPress")`（79741794）、`He()` = `clipboard.clear() → simulateCopy() → 500 ms 后读剪贴板`（79743310）、启停闸 `ipcMain.on(OPEN_DESKTOP_UPLOAD) → Se.start()`（79745740）。
可得行为链：右键长按 ≥250 ms（或 Ctrl+1，`keycode 2` 在码表里是数字键 `1`）→ 钩子投递 → `emit("longPress")` → 清空剪贴板 → 合成 Ctrl+C → 500 ms 后 `readFiles()` 读回选中内容 → 面板显示/上传。

**⑤ 端到端：模块启动即加载，钩子按需启动（2026-11-11 更正）**：早先记「起动真实客户端两批（120 s / 75 s），`/proc/<pid>/maps` 里 `uiohook` 与任何 `.node` 都是 0 行 ⇒ 钩子未加载」——**判据错误**：Electron 把 asar 内 `.node` 解包成**随机名临时文件**（实测 `/data2/tmp/.org.chromium.Chromium.PlVgmi`），路径里不含 `uiohook` 字样，按路径名搜必然零命中。

改用**字节身份判据**（读 `/proc/<pid>/map_files/<addr>` 算 SHA-256，与已提取哈希比对）做 A/B：control 组 = 启动后不发 IPC；trigger 组 = 经 CDP 在 renderer 执行 `require('electron').ipcRenderer.send('openDesktop', 300, true)`。

| 观测点 | control | trigger |
|---|---|---|
| 临时映射按 SHA-256 命中已知原生 | **3 个**（`uiohook_napi.node` 62,664 B / `NativeExtension.node` 14,040 B / `koffi.node` 5,944,784 B） | **3 个**（同左） |
| `app.log` 中 `hook_thread_proc` 行 | **0** | **1** |
| 关停时 `pre-stopping uiohook` / `fully released` | 0 / 0 | **1 / 1** |

⇒ 拆成两条不可互相替代的结论：**① 模块加载 = 冷启动即 dlopen**（control 组同样命中，对应 `core.asar` off 78833954 的 `e.exports = require("uiohook-napi")`）；**② 钩子线程 = 按需启动**（判据是 `hook_thread_proc … Could not set thread priority 49` 只出现在 trigger 组）。

IPC 频道字符串同时闭合：`OPEN_DESKTOP_UPLOAD` = **`"openDesktop"`**（`core.asar` off 78614860 / 78760702 / 88582424 三处同名常量）。完整证据卡：`~/rea-work-20261108/reports/2026-11-11-open-desktop-upload-loop.md`（SHA-256 `f4e934489b502fc8b57173b915e67ef4cf8facf9fe7eb40cc888018cf4edbeaa`），原始读数 `work/natives/dynamic/e2e_hash/{pre,post,control_post}.json`。

**⑥ 网络面（同轮补测）**：`tcpdump` 与 `strace -p` 在本机均被权限拒绝（缺 CAP_NET_RAW / ptrace_scope），改走 `ss -tnp` A/B 差分 —— trigger 组 30 s 内新增 6 个远端端点，control 组新增 3 个且**全部包含在 trigger 组集合内** ⇒ 属周期性心跳/埋点，非钩子引起。**只能写「未观测到外传」，不能写「无外传」**（TLS 不可解析、无 payload 关联）。

**⑦ 长按链闭环与网络面升档（2026-11-12 追加）**

**闸门是源码级可证的**：`Se.on("longPress",(e,n,t)=>{Ie.hide();const i=P.app.mainBrowserwindow;i&&i.isFocused()||(…He(),…)})`（`core.asar` off `79741792`，闸门 `i&&i.isFocused()||` 在 `79741862`）——**主窗口持焦点时整条链被静默跳过**。判据换成用户可见的面板文案（`t._v("剪贴板中的"+…+"个文件")`，off `6483241`）后，三条件 A/B：

| 条件 | 焦点持有者 | 剪贴板 | 面板 |
|---|---|---|---|
| A | app 主窗口 | 标记文本 | **不含**「剪贴板中的」（3/3，标记原样不动） |
| B | 自建 override-redirect 窗口 | 标记文本 | `He()` 第一步 `clipboard.clear()` 生效（标记 → 空） |
| C | 协作式第三方窗口（持焦点且持剪贴板） | `/tmp/probe_dtu/a.txt\r\n/tmp/probe_dtu/b.txt` | **5/5 命中**「剪贴板中的2个文件 / a.txt 等2个文件」 |

运行时指纹（`app8.log` 144 行，同一栈 6 次）：`longPressCallback (main.js:1:993049)` → `emit (1:648767)` → `Timeout._onTimeout (1:649461)` → `He (1:994303)` → `We (1:990784)` → `readFiles (1:650642)`。`hook_thread_proc` 只 1 条 ⇒ 钩子首轮按需启动后持续在跑。

两处 X11 结构事实（引用时常被写错）：**鼠标按钮重映射** `XTEST 1→button 1`、`XTEST 2→button 3`、`XTEST 3→button 2`（所以 `onMouseDown` 判 `3===e.button` 命中的是 X 中键）；**键盘** `XTEST(38)→uiohook 30`、`XTEST(50)→42`（减 8）。长按判定还可用 LF 坏载荷当廉价探针：`readFiles` 在 `JSON.parse` 抛 `Bad control character …`，栈里出现 `longPressCallback` 即为执行命中。

网络面从端点集合升到明文载荷（三档）：`ss -tnp`（IP）→ CONNECT 隧道代理（**明文 Host**，20 s 39 条 CONNECT / 12 端点，**全部百度自有域名，无第三方**）→ 现场签发叶证书的 MITM（**请求行 + 头 + POST body**，11 条解密，`POST /api/log/report/contentFe` 三条 `cl=bodyn=949/1065/978` + `POST /cap/log` 1381）。这批登录取证的 body 是 web-vitals 性能遥测（`PERFORMANCE: LCP` / `FPS_JANK_PAGE_VIEW` / `FPS: 48, Jank Rate: 0.021`）+ 本机环境指纹（UA / `cuid` / `tid` / `networkType`），**未见剪贴板内容或文件路径**。MITM 只解密 3 个 host —— CA 未被 app 信任（`app4.log` 21 次 `CertVerifyProcBuiltin … No matching issuer found`，覆盖 12 个 host），`--ignore-certificate-errors` 对 Electron `net::` 栈无效。

完整证据卡：`~/rea-work-20261108/reports/2026-11-12-longpress-clipboard-loop.md`（344 行，SHA-256 `12e79a5ea6f23cf5fbb17130c215e47ab4bd35b8322bcb15c9507fde219f04fa`；含 §7b SPKI pin、§7c 外传 A/B、§7d jnmq 明文捕获），原始读数 `~/rea-work-20261108/work/net-probe/longpress_loop_evidence/`（26 文件，`result.jsonl` 5/5）。

**⑧ MITM 上限解除 + 剪贴板内容外传的干净 A/B（2026-11-12 追加）**

**上限解除靠 SPKI pin，不靠装 CA**：把「所有叶证书共用一把固定密钥」（`openssl genrsa -out /tmp/mitm/leaf.key 2048`，叶证书统一由该密钥签）这步做了之后，才能算出**单一**的叶 SPKI `1rNIPyjFPElQ5iPJJoNErD//XCTK/ZWyM04hRlaRfuI=`；原版 `mitm2.py` 每 host 现签一把新密钥，SPKI 每 host 不同，无从 pin。app 加 `--ignore-certificate-errors-spki-list=…` 后 `CertVerifyProcBuiltin` **0 次**（旧路线 21 次）、**13 个 host 全解密**。

**SPKI 的语义边界（这句必须带）**：`curl --pinnedpubkey` 不带 `-k` 仍 rc=60 ⇒ **pin 只管公钥匹配，不替代信任链**；Chromium 能放行是因为它**同时跳过链校验**——这比「装 CA」更粗暴。

**外传问题的干净 A/B**：剪贴板放两个已知路径，先在渲染层经 CDP 发一次 `openDesktop`（**否则 `je()` 未执行、`Se.on("longPress")` 没注册，注入 `Ctrl+1` 得 `SUMMARY copied=False served=1`**——这是本轮踩到的第五个前置条件），再各 30 s 对比：control **新增 REQ = 0**；trigger 面板确认命中「剪贴板中的2个文件」而 **新增 REQ 也是 0**；needle 全文扫描（raw/urlquote/quote_plus 三形态，扫描器先用 curl 自检过靶）累计命中仍 3（全部 curl 自检）。

**剩余风险写明**：`POST /jnmq`（`xlab.baidu.com`）的 `p=`/`q=` 是 URL 编码 base64，解出 1,419 B 二进制（可打印比例 0.373），**字符串匹配对它无效**；且它是**周期节律**（60 s 内 5 次，`cl=660/14870/14894/678/918`），触发时刻只撞上一次，**不能当因果证据**。所以结论只能是「未观测到外传」，理由从「覆盖率不够」升级为「结构不可穿透」。

**方法论教训（可迁移，本卡踩了五次同一类错——把「我的仪器看不见」当成「不存在」）**：

- **第 1 次（`keyTap`）**：「没有观测到」必须先证仪器对靶。误判代价是把「注入能力已实测」写成「无能力」，根因是观测通道（XRecord）与被观测机制（`XSendEvent`）不同源。正确判据是「同一时刻两个观测者看到什么差异」（`send_event=0` vs `=1`），不是「我的仪器收到几条」。
- **第 2 次（maps 判据）**：阳性对照只证明了「按**路径名**能看见」，没证明「这条尺子对 Electron 的**随机名解包**也有效」。真正对靶的判据必须建立在**不随载体改名而变的身份**——这里是内容 SHA-256，读 `/proc/<pid>/map_files/<addr>` 而不是 `/proc/<pid>/maps` 的路径字符串。
- **第 3 次（CDP target）**：同一 URL `index.html#/login` 在 `/json` 里有 **2 个 page target**，只有 `hasFocus=true` 的那个活。按第一个 target 挂监听读到 0 条，责任在**看错对象**，不在机制。判据修法：遍历所有 target 逐个 arm/read，把 `hasFocus` 与 `vis`（`visible`/`hidden`）一起打出来。
- **第 4 次（第三方剪贴板应答）**：自造第三方窗口声明 CLIPBOARD 后 Electron 侧读到空串，第一反应是「掩码/加密」。真相是**协议应答不全**——Chromium 先要 `TARGETS`（须回 **32-bit atom 列表** `UTF8/STRING/TEXT`），且具体 target 的 property type 必须是**被请求的 atom 本身**。补齐后 `readText()`/`read('text/plain')` 同值、`availableFormats()=["text/plain"]`。这一类的特征是**前置条件没造对**，而失败现象长得像「目标拒绝」。
- **四次归因谱（值得当检查表用；第 5 次属于同一谱里的 (b)「仪器看不见」，第 6 次见 ⑨ 节新增的 (e)「把可解对象当成不可解」）**：「没有观测到」有四种病因——(a) 机制真的不存在；(b) 机制在、**仪器看不见**（XRecord 见不到 `XSendEvent`）；(c) 机制在、仪器对、**看错对象**（同 URL 两个 target）；(d) 机制在、仪器对、对象对、**我造的前置条件不成立**（`TARGETS` 没回、焦点被面板夺走）。每次的正解都是把判据换成「**另一条独立通道能否看到同一件事**」。
- **第 5 次（MITM 日志静默截断）**：`BODY[:2000]` 让 needle 落在 2001 字节之后时日志**看不出任何异样**——这不是「没命中」，是「没看全」。改成「哈希 + 头 400 字节 + 三形态全文计数」后才成立。**「我扫了全文还没命中」必须先证明「扫描器能命中我故意放进去的东西」**。
- 判据自检的正确形式是「注入一个已知存在的东西，看它能否被看见」，而不是「拿它的某个特征去搜」。

**⑨ `jnmq` 黑箱打开（2026-11-12 追加，方法论第 6 次）**

`jnmq`/`xlab` 在 `core.asar` 各 1 处命中（@39474843 / @38061421），但两处都落在同一片 **8,286,432 B 纯 base64 run `[33400599, 41687031)`**——run 前 `xlink:href="data:image/png;base64,`、run 后 `"/></defs></svg>`，那是一个**内嵌 PNG 的 data-URI**。随机 4-gram 对照（20 个随机串均值 0.3、理论期望 0.494；`jnmq`=1、`xlab`=1、`qqqq`=2）⇒ **巧合命中，不是端点定义**。

真正的发起方是上游 `hercules.cdn.bcebos.com/pass/bundle.js` 的 `la()`：`navigator.sendBeacon(url, new Blob(['q='+lQ]))`，`url` 取自上下文对象 `lV` 的 `url` 字段（`"https://xlab.baidu.com/jnmq"`，`lV` 另带 `version:"1.0.10"`、42/28 个短键、`T:["ccq","cdo","sl","mj","ra","pg"]`）⇒ **端点是登录页 SDK 自己拼的，不在客户端安装面内**。外层 `setTimeout(...,0x7530)` 就是那个 30 s 周期节律。

CDP 断点放在**加密之前**的函数帧上，直接读到明文（不是解密密文）：

| 路径 | 帧 | 明文长度 | 结构 |
|---|---|---|---|
| `q=` | `ll(ld,lN,lQ)` | 463 / 478 B | `at/gt/href/referrer/n/ec` + `icc`（行为计数器）+ `dks`/`dms`/`dos` |
| `p=` | `sI` | 126 B | `{v:"1.0", d:<内层密文>, c:<会话标识>}` 信封 |

按键段 `kl` 从 `{"kc":0,"sk":0,"iv":[]}` 变为 **`{"kc":5,"sk":0,"iv":[18133,4,3,1,1]}`**（从 `page` target 注入 a/b/c/d/e 五键）⇒ `kc` 是击键**次数**、`sk` 是修饰键次数、`iv` 是**击键间隔毫秒数组**（首项 18,133 是距会话起点）。静态印证 `bundle.js:235546` 的 `'kc':…['cr'],'sk':…['ur'],'iv':…['dr']`，`ur` 对 `keyCode ∉ {0x10,0x11,0x12,0x5b,0x08}` 计数。⇒ **只记次数与间隔，不记键值**。

剪贴板标记（`UNIQUE_MARKER_7788123456`，由 X 侧独立进程在 app 启动前持有 CLIPBOARD 所有权）在 18 条 HIT 里 **`markerHits = 0`** ⇒ 两条明文路径都不含剪贴板内容。证据包：`~/rea-work-20261108/work/net-probe/jnmq_plaintext_evidence/`（7 文件 / 84 K）。

**方法论教训第 6 次（归因谱新增一类 (e)）**：「不可解的载荷」不等于「永久黑箱」。上一版把 `jnmq` 写进「剩余风险」是对的（当时只能做字符串匹配），但把它当终点是偷懒——**只要明文在被加密之前存在过，就一定有某个时刻能被读到**。判据顺序应当是「能拿明文就先拿明文，拿不到才退回匹配密文」。另附六次仪器纠错：①`setBreakpointByUrl` 返 `locs: []` 当无效删断点（实为脚本未加载）；②按 `callFrame.url` 匹配（`paused` 里是空串）；③按变量名 `evaluateOnCallFrame` 撞闭包同名 function；④`241117` 实为 `ll` 不是 `la`（形参 `ld/lN/lQ` 遮蔽）；⑤app 起来后才 attach / 靠 reload 重发（首帧 5 s 内发完且 reload 不重发）；⑥`Input.dispatchKeyEvent` 发 webview target 0 条到达，必须发 `page` target 且先 `webview.focus()`。

## 边界（不得越过）

1. **反编译 ≠ 源码**。pseudocode 是 Ghidra 12.1.3 表示；结论只到「调了哪些 X11 / N-API 函数」，不到意图层。
2. **只在 X11 分支成立**。Windows 走 `SET_WINDOWS_HOOK_EX`、macOS 走 AXAPI，本次未分析对应二进制。
3. ~~**没有动态观测**~~ **2026-11-10 已补，2026-11-11 更正第三点，见上节「动态补测」**：钩子确实收本地输入（XTEST 1:1）；`keyTap` 确实向焦点窗口投递合成事件（`send_event=1`）；模块**冷启动即加载**、钩子线程**按需启动**（不是「不加载」）。仍不能写「实测到键盘事件外泄」——网络面已升到明文载荷（见 3b），**未观测到**外传但未证否。⚠️ 不可再引用「冷启动期间不加载该 `.node`」，该结论建立在按路径名搜 `uiohook` 的错误判据上，已撤回。
3b. **网络面的表达上限（2026-11-12 更新）**：`tcpdump`（缺 CAP_NET_RAW）与 `strace -p`（ptrace_scope）均不可用，但可改用**代理**取明文——CONNECT 隧道代理（只解 Host）与现场签发叶证书的 MITM（能看请求行 + 头 + POST body）。即便如此：MITM 只解密了 3 个 host（CA 未被 app 信任，`--ignore-certificate-errors` 对 Electron `net::` 栈无效），且「control 端点集合 ⊆ trigger 端点集合」只否证「钩子引起新增端点」，不否证「已有的心跳连接承载了事件内容」。**2026-11-12 起该边界已两次收紧：SPKI pin 让 13 个 host 全解密（`CertVerifyProcBuiltin` 0 次），唯一曾不可解的 `jnmq` 已按加密前明文判定（见 ⑨）。仍未证的是：密文本身未离线解（key 由种子数组现算）、只测了无修饰键击、变体未穷举。所以仍写「未观测到」，但理由从「结构不可穿透」变成「明文面零命中 + 唯一黑箱已按明文判定，剩余三条窄口子已列明」。**
3c. **剪贴板闭环的第三方窗口是我们自己写的**。它证明「应用会向**当前焦点窗口**发合成 `Ctrl+C` 并把剪贴板内容读回来」，**不证明**对任意真实应用都能取到（真实应用未必按协议应答：实测 `xedit` 在 `:99` 上根本不绑 `Ctrl+C`，用它会得到假阴性）。另外 `:99` **无窗口管理器**，焦点行为与真实桌面不同；`isFocused()` 闸门本身是源码级可证的（off `79741862`），不依赖本环境。
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
