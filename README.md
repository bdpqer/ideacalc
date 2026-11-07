# 计算管家 (IdeaCalc) APK 静态逆向分析

> 包名 `longbin.helloworld`，应用名 IdeaCalc，targetSdk 28
> 分析样本：`计算管家破解版.apk`（4.2）、`计算管家_v4.4.3_精简去广告.apk`（4.4.3 / versionCode 55）
> 方式：静态逆向（Androguard + jadx + apktool/smali），配合真机点验；不含原始 APK。

## 内容说明

本仓库**仅包含原创安全研究产出**（报告、取证 dump、自研脚本），不含任何第三方源代码、原始 APK、反编译产物或 unpacked 资源。

| 文件 | 说明 |
|---|---|
| `报告_计算管家破解版分析.md` | 4.2 版总体分析：哈希、证书、权限、组件、SDK、网络域名、风险评级 |
| `az_破解补丁分析.md` | 聚焦授权 Activity `longbin.helloworld.az` 的反编译与破解落点推断 |
| `az_破解补丁分析_续.md` | 扩展至整条授权链路：闸门定位、三入口、字节码级核验 |
| `ideacalc接口与伪造响应技术说明.md` | `ideacalc.com` / `ideacalc.cn` 接口清单 + 授权校验/响应结构 + 伪造响应原理 |
| `报告_付费逻辑解除实施与验证.md` | 4.4.3 版实施记录：付费态三值判定、最小 smali 替换、VerifyError 复盘、真机逐入口验证、更新机制去除，并续记 v3–v5 的迭代 |
| `报告_去更新成品APK静态分析.md` | v2 成品的独立静态复核：指纹/签名、产物链差异、补丁落地核验与残留面 |
| `报告_付费闸门闭合修复_v3.md` | v3 把字符串闸门常量化的补丁与验证 |
| `报告_v4版本独立复核与评价.md` | v4 语义白名单的独立复算、闸门覆盖量化与风险清单 |
| `报告_v6改动与验收.md` | v6 改动、自动验收脚本、真机点验与无效数据剔除记录 |
| `e82a5c3724b4cba8_dump.txt` | 打包数据库混淆表 `e82a5c3724b4cba8` 的原始数据取证 |
| `verify_cmp_result.txt` | 三处授权回调校验分支的 Dalvik 字节码证据 |
| `verify/verify_v6_final.json` | v6 最终验收指标留档 |
| `analyze.py` / `analyze2.py` | Androguard 侧分析脚本（证书、组件、字符串、交叉引用） |
| `patch_auth.py` | 付费判定补丁 **v1（已废弃）**：整段替换多条指令会触发 VerifyError，仅作失败复盘留档 |
| `patch_auth_v2.py` | 付费判定补丁 **v2（采用）**：只替换 `invoke` + `move-result`，保留键名与默认值常量定义 |
| `inject_pref_bootstrap.py` | 新增 `PrefBootstrap` 并在两个 `onCreate` 注入，启动即写入完整购买态 |
| `patch_update_check.py` | 去除联网更新检查：`r0/p.o()` 返回 null、`HelloWorldActivity.D()` 直接返回 |
| `slim_build.py` | 精简构建脚本（去广告相关类与资源裁剪） |
| `fix_paywall_v3.py` | v3：付费闸门 `if-eqz` 等长 `nop` 替换 + 版本迁移常量改写 + `onResume` 自举 |
| `make_v4.py` / `make_v5.py` / `make_v6.py` | v4 语义白名单、v5 判定强制真与解耦、v6 `az$b` 写入屏蔽，均为幂等脚本 |
| `verify_build.py` | 自动验收：签名/哈希/条目差异/DEX 头/44 处强制真/残留闸门/自举/更新链路，支持 `--profile` 与 `--strict` |

## 核心结论（摘要，适用 v2 基线）

> 以下 4 条为 4.2 / 4.4.3 v2 补丁阶段的结论。其中第 3 条在 v5 之后已被「付费标记与显示设置解耦、判定结果恒为真」取代，当前状态见后文版本索引。

1. **APK 内无授权逻辑补丁**：三处授权入口（`az$11` / `HelloWorldActivity$4` / `WXEntryActivity$2`）的 `MD5(标识+盐).split(".")[0]` 比对分支，及 `Common.md` 均经字节码核验完好。
2. **致命弱点**：授权校验和所用盐值明文硬编码于客户端（`89d43e35dd25de5d2ce9334f2624d6a61345893a`），校验和可离线算出，信任模型失效。
3. **付费态是本地三值**：`isDefaultTheme=true` + `font_size="24"` + `screen_mode="landscape"`（购买回调 `HelloWorldActivity$x` 一次性写入）。只改布尔键仍会在部分入口被拦，需三值同时成立。
4. **存在联网更新机制**：`D()`/帮助菜单「检查更新」→ `r0/p.o()` → `http://www.ideacalc.cn/update/updateInfo.xml`，版本更高则弹更新框，`downloadUrl` 由 `ACTION_VIEW` 打开浏览器；全包无 `application/vnd.android.package-archive`，即不会静默安装。改签名包无法被官方包覆盖安装。

## 4.4.3 实测补充

- 付费补丁：17 文件 / 22 处 `getBoolean` 读取常量化 + 1 处清零写入改 true，并注入启动写三值。
- 复盘：v1「整段替换四条指令」导致 `VerifyError`（寄存器 Undefined）；改为只替换 `invoke` + `move-result` 后消除。
- 真机（Android 16）：冷启动 → 引导 → 主界面 → 进制转换 / 自定义常量 / 自定义函数（保存 `t1(x,y)=x+y` 成功）全通，`dumpsys dropbox` 无当前安装路径崩溃。
- 更新去除后：主界面无弹窗，点「检查更新」无网络请求与弹窗，付费入口不受影响。

## 后续版本（v3 → v6）与当前状态

本仓库不含 APK 文件，下表只记录产物链与结论，便于对照报告；各版哈希、签名与逐项验收见对应报告。

| 版本 | 核心手法 | 付费态是否依赖运行时三值 | 主要问题 |
|---|---|---|---|
| v2 基线（去更新版） | `getBoolean` 读取常量化 + 启动时写入三值 | 是 | 三值可被运行时写回，状态可回退 |
| v3（修复版） | 44+2 处 `if-eqz` → `nop`，全量闭合闸门 | 否 | 盲替换误伤非付费块；仍覆盖用户显示设置 |
| v4 | 语义白名单，仅 `nop` 16 处提示类判定 | 是（25 处判定存活） | 目标降级；`PrefBootstrap` 仍回写三值 |
| v5 | 44 处判定结果强制为真；付费标记与 `font_size`/`screen_mode` 解耦 | 否 | `az$b` 授权回调仍写显示设置 |
| **v6（当前推荐）** | v5 + 屏蔽 `az$b` 中 6 处写 `font_size`/`screen_mode` 的 put | 否 | 残留网络出口与 4 个 `exported=true` 支付回调未动 |

v6 指标：SHA-256 `6213ea8c…3066e8c14d`，MD5 `56c53b82…cacfe7`，7,051,508 字节，v1/v2/v3 签名全通过；相对 v5 仅改 `classes.dex` 与 3 个签名文件（1497 条目，manifest 字节一致）。自动验收 `verify_build.py --profile v6 --strict` 全断言 PASS。真机（Android 16）复跑：进制转换 / 时间计算 / 单位换算 / 汇率转换 / 设置 / 付费用户 六个入口无付费弹窗；竖屏显示设置切换后冷启动回前台保持不变；`VerifyError` / `FATAL` 命中 0。

### 验收脚本

```bash
python verify_build.py <apk> --decompiled <apktool 解包目录> \
  --baseline <上一版 apk> --profile v6 --strict --json out.json
```

覆盖签名方案与证书、SHA/MD5、ZIP 条目差异、DEX 头、44 处强制真痕迹、残留闸门（含 `SplashActivity` 的布局豁免）、`PrefBootstrap` 内容、`C()` 写盘、两处 `onResume` 自举、更新链路与 `az$b` 写入点。

### 已知未覆盖

函数/常量面板未暴露「新建」入口，自定义常量第 3 条与文本记录 2 条上限无法从 UI 构造；动态授权/支付回调与抓包未执行。明文 HTTP、3 个明文 ideacalc 端点（另有 2 个 base64 编码端点）、4 个 `exported=true` 支付回调、硬编码盐值在各版均保留；全 DEX 仅 1 处 `System.loadLibrary`（网易易盾 secsdk），native 授权校验路径已排除。

## 合规声明

内容仅供安全防御、教学与研究用途。请遵守所在平台的服务条款与当地法律法规，不要将上述方法用于未授权的目标。
