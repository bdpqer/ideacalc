# 计算管家 v4.4.3「精简去广告 / 去授权 / 去更新」成品 APK 静态分析

> 样本：`计算管家_v4.4.3_精简去广告_去授权_去更新.apk`（7,063,796 字节）
> 分析日期：2026-11-07
> 方法：ZIP 条目级比对、`apksigner verify`、`aapt dump badging`、apktool 2.9.3 反编译、smali 全量正则扫描、多层 base64 递归解码
> 性质：**纯静态复核**。本轮未连接真机、未安装运行、未抓包；既有报告中的真机结论未被重复验证。

---

## 一、结论先行

1. 样本确为产物链终点，指纹与既有报告完全吻合：SHA-256 `1C16FF13E377156F5DAADFE546E2F4B748353F1DFBD980823F07D64C6A736076`，签名证书 `CN=Android Debug` / `58e1ebd4…81ead`。v1/v2/v3 签名全部有效。
2. **补丁边界极干净**：`精简去广告 → 去授权 → 去更新` 两轮各只改动 `classes.dex` + 3 个签名文件，1497 个 ZIP 条目中资源、清单、assets、lib 全部零改动。
3. 三项改造在成品 DEX 中均实测落地：广告/统计/一键登录 SDK 方法体已 stub 化；授权侧有效 `getBoolean` 读取残留 **0**；更新侧 `r0/p.o()` 返回 null、`HelloWorldActivity.D()` 直接 return-void，`updateInfo.xml` 字符串已从 DEX 消失。
4. **最大结构性风险**：付费闸门只 patch 了布尔分支，`font_size="24"` / `screen_mode="landscape"` 的字符串比较原样保留（DEX 中 25 处 `"24"`、24 处 `"landscape"` 字面量判定，分布在 19–20 个文件）。付费态整体依赖 `PrefBootstrap` 在每次启动时写值维持，而 DEX 中仍存在**动态解码键名的隐藏写入路径**与**版本迁移写入**，可在运行中把三值改回免费态，补丁未覆盖。
5. 残留攻击面：全局允许明文 HTTP、5 个 ideacalc 服务端授权/支付接口、4 个 `exported=true` 支付回调 Activity、MD5 盐值硬编码、第三方 SDK 类与 4 个 `.so` 保留。

---

## 二、样本指纹与签名

| 项 | 值 |
|---|---|
| 文件大小 | 7,063,796 字节 |
| SHA-256 | `1C16FF13E377156F5DAADFE546E2F4B748353F1DFBD980823F07D64C6A736076` |
| ZIP 条目 | 1497（未压缩合计 12,330,724 字节） |
| DEX | 单个 `classes.dex`，5,198,360 字节，SHA-256 前缀 `5976c98e81792035` |
| DEX 结构 | 6253 类 / 48,366 方法 / 7,739 类型 / 38,508 字符串 |
| 包名 / 版本 | `longbin.helloworld`，versionCode 55，versionName 4.4.3 |
| SDK | minSdk 21 / targetSdk 28 / compileSdk 29 |
| 签名 | v1 ✅ v2 ✅ v3 ✅；v3.1 ❌ v4 ❌；单签名者 |
| 证书 | `CN=Android Debug, O=Android, C=US`，RSA 2048，SHA-256 `58e1ebd4c221468a6263b93a4bcb7e33f0e2f52965483b6da8425fa2a8981ead` |
| APK Signing Block | 位于文件偏移 6,934,512（v2/v3 块存在） |

签名与官方包不同，覆盖安装前必须卸载旧版。

---

## 三、产物链的条目级差异

| 对比 | 新增 | 删除 | 内容变化 |
|---|---|---|---|
| 原版 → 精简去广告 | 1199 | 1245 | 54 |
| 精简去广告 → 去授权 | 0 | 0 | **4**（classes.dex + MANIFEST.MF + ANDROIDD.SF/RSA） |
| 去授权 → 去更新 | 0 | 0 | **4**（同上） |

DEX 头数据可交叉印证三步改造：

| 版本 | DEX 大小 | 类 | 方法 | 字符串 |
|---|---|---|---|---|
| 原版 | 6,098,016 | 6252 | 49,131 | 42,704 |
| 精简去广告 | 5,198,696 | 6252 | 48,364 | 38,511 |
| 去授权 | 5,198,820 | **6253** | **48,366** | 38,513 |
| 去更新（本样本） | 5,198,360 | 6253 | 48,366 | **38,508** |

- 精简阶段类数不变、字符串少 4193 → 符合「保留类名与方法签名，只清空方法体」。
- 去授权多出 1 个类 / 2 个方法 → 正是新增的 `PrefBootstrap`（构造 + `a(Context)`）。
- 去更新字符串少 5 → 两个方法体被整体替换，内部常量被移除。

原版 → 精简删除的关键项：`assets/gdt_plugin/gdtadv2.jar`（广点通插件）、`assets/supplierconfig.json`、`libumeng-spy.so`、`libalicomphonenumberauthsdk_core.so`、`res/aD.xml`、36 个 META-INF 版本文件；同时 apktool 重打包导致 res 条目整体重排（1198 删 / 1197 增），并非业务性删减。

---

## 四、去广告实现复核（`slim_build.py`）

策略是 **stub 化而非删除**：对 `com/qq/e`（广点通）、`com/umeng`、`com/mobile/auth`、`com/nirvana`、`com/cmic`、`com/alicom`、`com/bun` 七个包，保留类、构造与方法签名，把非抽象方法体替换为安全返回值。抽查 `com/qq/e/ads/AbstractAD$1$1.smali` 等，`run()` 已为 `.locals N` + `return-void`，构造函数保留。

配套动作：
- 清单删除 20 个 SDK 组件声明与 10 项权限（`READ_PHONE_STATE`、`ACCESS_COARSE_LOCATION`、`REQUEST_INSTALL_PACKAGES`、`QUERY_ALL_PACKAGES`、广告 ID 相关等）。
- 短路自有入口：`HelloWorldActivity.b0()`、`SplashActivity.d/h/l()`；启动页 `g()` 的 1500ms 等待改为 0。
- 体积从 9,785,477 降至 7,063,796 字节。

残留：SDK 的 Java 类仍在 DEX 中（只是空实现）；`lib/arm64-v8a|armeabi-v7a` 下仍保留 `libpns-2.12.10-…alijtca_plus.so` 与 `libsecsdk.so`；`SplashActivity.onCreate` 仍有友盟 `UMConfigure.preInit`（AppKey 硬编码 `541435b6fd98c50ae307da98`，调用已落入空实现）；FileProvider 仍引用 `@xml/gdt_file_path`。

---

## 五、去授权实现复核

### 5.1 补丁落地（已验证）

- `isDefaultTheme` 字面量出现在 20 个文件 / 27 处；按 `patch_auth_v2.py` 的判定规则（回溯 500 字符确认 key 寄存器来源）扫描，**未替换的有效 `getBoolean` 读取点 = 0**。
- 两处 `putBoolean("isDefaultTheme", …)`：购买成功回调原本写 true；`HelloWorldActivity.C()` 的升级清零点已被插入 `const/4 v1, 0x1` 强制写 true（smali 第 948–952 行）。
- 新增 `PrefBootstrap.smali`，`a(Context)` 写入 `isDefaultTheme=true` / `font_size="24"` / `screen_mode="landscape"` 并 `commit()`。
- 调用点：`SplashActivity.onCreate`（第 616 行）与 `HelloWorldActivity.onCreate`（第 13725 行），均在 `invoke-super` 之后紧接插入，无需改 `.locals`。

### 5.2 结构性盲区（本轮新发现）

**(1) 字符串闸门完全未 patch。** DEX 中仍存在 25 处 `"24"`、24 处 `"landscape"`、26 处 `"font_size"`、25 处 `"screen_mode"` 字面量，分布在 19–20 个文件，各功能入口的 `equals("24")` / `equals("landscape")` 比较原样执行。布尔键已被常量化为 true，但两个字符串键仍是「活」的判定，只靠启动时写值维持。

**(2) 存在动态解码键名的隐藏写入路径。** `az$b.smali`（支付/授权回调）通过 `r0/f->b()` 运行时解码键名后执行 `putString` / `putBoolean`，共 3 组、每组 4–6 次写入；`a.smali` 中递归解码多层 base64 可得 `font_size`、`screen_mode`、`isDefaultTheme`、`24`、`landscape`、`buyer_account`、`expired_time` 等明文。`patch_auth_v2.py` 只匹配 `const-string "isDefaultTheme"` 字面量，**这些解码后写入不受补丁约束**，可在运行中把付费三值改写。

**(3) 版本迁移写入位于自举之后。** `HelloWorldActivity.C()` 在 onCreate 第 9615 行被调用（晚于第 13725 行的 `PrefBootstrap`）。当 `savedVersionCode != 0` 且当前 versionCode 更大时，会写 `font_size="26"`、`screen_mode="normal"`（`isDefaultTheme` 已被 patch 为 true），**直接破坏两个字符串闸门**。首次安装 / 清数据后 `savedVersionCode=0`，走 `:cond_0` 分支，不触发该写入——因为本包必须卸载旧版才能安装，正常路径不受影响；但备份恢复、跨版本升级或数据迁移场景会命中。

**(4) 服务端授权链路完整保留。** 递归解码得到 5 个明文 HTTP 接口：

```
http://ideacalc.cn/check_authorization_by_account_and_equipment_id.php
http://ideacalc.cn/check_authorization_by_para.php
http://ideacalc.cn/get_payinfo_by_account_cn.php?buyer_account=
http://ideacalc.cn/get_payinfo_by_account_en.php?buyer_account=
http://ideacalc.cn/get_expired_time.php?equipment_id=
```

另有 `http://www.ideacalc.cn/wxpay/notify_url.php`、`https://api.mch.weixin.qq.com/pay/unifiedorder`。MD5 盐值 `89d43e35dd25de5d2ce9334f2624d6a61345893a` 仍明文硬编码于 `az$b.smali:360` 与 `wxapi/WXEntryActivity$b.smali:90`。

> 结论：补丁是「本地判定常量化 + 启动自举」，不是「移除授权体系」。离线可用，联网授权回调仍有能力改写状态。

---

## 六、去更新实现复核（已验证）

| 方法 | 成品方法体 | 效果 |
|---|---|---|
| `r0/p;->o()Lr0/k;` | `.locals 4` / `const/4 v0, 0x0` / `return-object v0` | 不再发起 HTTP 请求，handler 走空结果分支 |
| `HelloWorldActivity;->D()V` | `.locals 10` / `return-void` | 定时判断与 `lastUpdateCheckTime` 写入均不执行 |

`updateInfo.xml` 字符串在最终 DEX 中已检索不到（原字符串数 38,513 → 38,508，与删除常量吻合）。方法体为整体替换、无死代码，规避了首版 `VerifyError` 的寄存器 Undefined 问题。

**仍然存活的其它联网接口**（非更新链路）：`http://www.ideacalc.cn/data/paras.xml`、`http://www.ideacalc.cn/data/video.xml`、`http://ideacalc.cn/submit_suggestion_by_device.php?name=`，以及大量第三方 SDK 域名（umeng 上报、支付宝网关、运营商一键登录、优酷/YouTube 帮助视频等）。应用层 `usesCleartextTraffic="true"` 且 `network_security_config.xml` 为 `<base-config cleartextTrafficPermitted="true" />`，全局允许明文 HTTP。

---

## 七、清单与攻击面

| 项 | 数量 | 说明 |
|---|---|---|
| Activity | 28 | 20 个带 `intent-filter`（多为仅 `category LAUNCHER`、无 action，实际不导出） |
| Provider | 1 | `android.support.v4.content.FileProvider`，`exported=false`，`grantUriPermissions=true` |
| Service / Receiver | 0 | 已在精简阶段全部移除 |
| `exported=true` | **4** | `WXPayEntryActivity`、`WXEntryActivity`、`com.alipay.sdk.app.PayResultActivity`、`com.alipay.sdk.app.AlipayResultActivity` |
| `exported=false` | 4 | 支付宝 3 个 + FileProvider |
| 权限 | 7 | VIBRATE、READ/WRITE_EXTERNAL_STORAGE、INTERNET、ACCESS_NETWORK_STATE、ACCESS_WIFI_STATE、REORDER_TASKS |
| application | — | `allowBackup=false`，无 `debuggable`，`usesCleartextTraffic=true` |

4 个导出的支付回调 Activity 是本包最直接的外部入口；它们背后的支付/授权回调正是第 5.2 节所述的状态改写通道。建议若不打算真实支付，可将其 `exported` 置 false 或直接 stub 掉回调写入。

---

## 八、与既有报告的偏差 / 补充

1. 报告称「原 DEX 中的三处 MD5 授权校验入口」——本轮明文盐值仅在 **2 处**检出（`az$b.smali:360`、`wxapi/WXEntryActivity$b.smali:90`）；第三处未以明文复现。但解码后发现 **5 个**服务端授权/查询接口，联网校验入口实际多于三处。
2. 报告称「离线不触发，仅在联网校验时会走原逻辑」——补充：该回调通过动态解码键名写 SharedPreferences，属于**运行时回滚付费态**的通道，不只是「走原逻辑」。
3. 报告第七节「未逐个点验：主题风格、统计、循环小数互化、文本记录历史」保持成立，本轮为静态分析，未补做。
4. 报告第九节「字符串混淆为双重 base64」——实测存在**三层及以上**嵌套（如 `buyer_account` 需解 3 层），仅解两层会停在中间态。

---

## 九、风险清单与建议

| 级别 | 风险 | 建议 |
|---|---|---|
| 高 | 两个字符串闸门未 patch，付费态仅靠启动时写值维持；动态解码键名的授权回调可运行时改写 | 把三值字符串比较也常量化，或在 `az$b` / `a.smali` 的写入点统一屏蔽；在 `onResume` 重新自举 |
| 中 | `HelloWorldActivity.C()` 版本迁移在自举之后写 `font_size="26"` / `screen_mode="normal"` | 将 `C()` 中该段一并 patch，或把 PrefBootstrap 调用移到 `C()` 之后 / `onResume` |
| 中 | 4 个 `exported=true` 支付回调 Activity | 置 `exported=false` 或 stub 回调写入 |
| 中 | 全局明文 HTTP + 5 个授权接口 + 硬编码盐值 | 收紧 `network_security_config`；无需联网时可移除 INTERNET 或屏蔽这些接口 |
| 低 | SDK 类/`.so`/FileProvider 路径残留 | 仅影响体积与静态观感，stub 化后不产生实际行为 |

---

## 十、复现命令

```bash
cd D:/project/IdeaCalc
sha256sum 计算管家_v4.4.3_精简去广告_去授权_去更新.apk
java -jar build-tools/android-14/lib/apksigner.jar verify --verbose --print-certs 计算管家_v4.4.3_精简去广告_去授权_去更新.apk
./build-tools/android-14/aapt.exe dump badging 计算管家_v4.4.3_精简去广告_去授权_去更新.apk
java -jar apktool.jar d -f -o work/analysis_final 计算管家_v4.4.3_精简去广告_去授权_去更新.apk
```

解包产物位于 `work/analysis_final/`（AndroidManifest.xml、smali/、res/、assets/、lib/）。

---

## 十一、验证状态

- **已验证（本轮静态）**：指纹、签名方案与证书、ZIP 条目差异、DEX 头统计、清单组件与导出面、三项补丁的 smali 落地、付费闸门字面量统计、动态解码键名路径、残留网络端点。
- **未执行（本轮）**：真机安装与功能点验、动态触发联网授权回调、网络抓包、DEX verifier 实机检查、主题/统计/循环小数/文本历史入口点验。既有报告第六节与第 10.4 节的真机结论为本轮唯一依据，未重复验证。
- **建议补测**：① 有 `savedVersionCode` 旧数据恢复后启动，验证自定义函数是否仍可新增；② 主动触发一次「检查授权/支付回调」，观察后续功能入口是否被拦；③ 抓包确认离线状态下是否还有对外请求。
