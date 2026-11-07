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
| `报告_付费逻辑解除实施与验证.md` | 4.4.3 版实施记录：付费态三值判定、最小 smali 替换、VerifyError 复盘、真机逐入口验证、更新机制去除 |
| `e82a5c3724b4cba8_dump.txt` | 打包数据库混淆表 `e82a5c3724b4cba8` 的原始数据取证 |
| `verify_cmp_result.txt` | 三处授权回调校验分支的 Dalvik 字节码证据 |
| `analyze.py` / `analyze2.py` | Androguard 侧分析脚本（证书、组件、字符串、交叉引用） |
| `patch_auth.py` | 付费判定补丁 **v1（已废弃）**：整段替换多条指令会触发 VerifyError，仅作失败复盘留档 |
| `patch_auth_v2.py` | 付费判定补丁 **v2（采用）**：只替换 `invoke` + `move-result`，保留键名与默认值常量定义 |
| `inject_pref_bootstrap.py` | 新增 `PrefBootstrap` 并在两个 `onCreate` 注入，启动即写入完整购买态 |
| `patch_update_check.py` | 去除联网更新检查：`r0/p.o()` 返回 null、`HelloWorldActivity.D()` 直接返回 |
| `slim_build.py` | 精简构建脚本（去广告相关类与资源裁剪） |

## 核心结论（摘要）

1. **APK 内无授权逻辑补丁**：三处授权入口（`az$11` / `HelloWorldActivity$4` / `WXEntryActivity$2`）的 `MD5(标识+盐).split(".")[0]` 比对分支，及 `Common.md` 均经字节码核验完好。
2. **致命弱点**：授权校验和所用盐值明文硬编码于客户端（`89d43e35dd25de5d2ce9334f2624d6a61345893a`），校验和可离线算出，信任模型失效。
3. **付费态是本地三值**：`isDefaultTheme=true` + `font_size="24"` + `screen_mode="landscape"`（购买回调 `HelloWorldActivity$x` 一次性写入）。只改布尔键仍会在部分入口被拦，需三值同时成立。
4. **存在联网更新机制**：`D()`/帮助菜单「检查更新」→ `r0/p.o()` → `http://www.ideacalc.cn/update/updateInfo.xml`，版本更高则弹更新框，`downloadUrl` 由 `ACTION_VIEW` 打开浏览器；全包无 `application/vnd.android.package-archive`，即不会静默安装。改签名包无法被官方包覆盖安装。

## 4.4.3 实测补充

- 付费补丁：17 文件 / 22 处 `getBoolean` 读取常量化 + 1 处清零写入改 true，并注入启动写三值。
- 复盘：v1「整段替换四条指令」导致 `VerifyError`（寄存器 Undefined）；改为只替换 `invoke` + `move-result` 后消除。
- 真机（Android 16）：冷启动 → 引导 → 主界面 → 进制转换 / 自定义常量 / 自定义函数（保存 `t1(x,y)=x+y` 成功）全通，`dumpsys dropbox` 无当前安装路径崩溃。
- 更新去除后：主界面无弹窗，点「检查更新」无网络请求与弹窗，付费入口不受影响。

## 合规声明

内容仅供安全防御、教学与研究用途。请遵守所在平台的服务条款与当地法律法规，不要将上述方法用于未授权的目标。
