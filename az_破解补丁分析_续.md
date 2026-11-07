# `longbin.helloworld.az` 破解补丁逆向分析 · 续篇（授权闸门与全链路核验）

> 承接 `az_破解补丁分析.md`。本篇把分析从 `az` 单类扩展到了**整个授权链路**，并用**字节码级**手段核验了所有校验分支。
> 工具：Androguard 3.x + DAD 反编译器（纯 Python，无 JDK）。

---

## 〇、上一轮留下的疑点

上一轮已确认 `az$11.handleMessage` 的校验和分支 `if (!checksum.equals(parts[0]))` 在字节码中完好。由此推得：破解版**没有删/改 `az` 的校验门**，而是「喂一个本地算出的合法校验和响应」。
本篇要回答：**这个「喂响应」的补丁到底落在哪？** 以及 **真正判定「已付费」的闸门在哪？**

---

## 一、真正的「付费闸门」是 `isDefaultTheme`

反编译启动页 `SplashActivity.onCreate`（第 204–234 行）：

```java
String v0_0 = this.defaultSharedPreferences.getString("font_size", "28");
boolean v1_1 = this.defaultSharedPreferences.getBoolean("isDefaultTheme", 0);  // ← 闸门标志
if (!this.isGuided()) {
    // 首次运行 → GuideActivity
} else {
    if ((!"zh-CN".equals(this.getLocaleLanguage())) || ((v0_0.equals("24")) && (v1_1))) {
        SplashActivity.showHome(this);   // ← 直接进主界面（付费/已授权路径）
    } else {
        this.setContentView(this.getContentView());  // ← 否则看开屏广告
    }
}
```

**关键事实：**
- 授权判定**纯本地**：只读取 `SharedPreferences` 里 `isDefaultTheme`（布尔）和 `font_size=="24"`，**完全不比对到期时间**。
- 全 DEX 中 `expired_time`、`now_time` 的明文**零引用**——之前以为按「到期时间」判定是误会，实际只是把到期时间存进数据库做记录，并不参与放行判断。
- `isDefaultTheme` 作为明文键被 **26 处**读取（SplashActivity / GuideActivity / 各功能 Activity / 多个按钮监听），是事实上的付费开关。

---

## 二、哪些代码会写入 `isDefaultTheme=true`（全部走校验和）

通过字符串交叉引用，定位到**三个**把授权写入 `isDefaultTheme` 的入口，逻辑同构：

| 入口 | 触发 | 校验公式 |
|------|------|----------|
| `az$11.handleMessage`（case 1003） | 账号授权网络回调 | `MD5(account + 盐).account.到期.订单` |
| `HelloWorldActivity$4.onResponse` | 主界面授权网络回调 | `MD5(out_trade_no + 盐).账号.到期.订单` |
| `wxapi/WXEntryActivity$2.handleMessage` | 微信授权回调 | `MD5(account + 盐).账号.到期.订单` |

三者都做同一件事：本地算 `Common.md(标识 + "89d43e35dd25de5d2ce9334f2624d6a61345893a")`，与服务端响应 `split(".")[0]` 比对，**一致**才写 `isDefaultTheme=1` + `buyer_account/expired_time` 到 SharedPreferences 与混淆表 `e82a5c3724b4cba8`。

---

## 三、字节码级核验：三个校验分支全部完好（铁证）

对三个入口提取 Dalvik 指令，比较点无一例外是「算 MD5 → split → equals → if-eqz」：

**`HelloWorldActivity$4.onResponse`**
```
[0020] const-string "89d43e35dd25de5d2ce9334f2624d6a61345893a"   ← 盐值
[0024] invoke Common.md(...)                  ← MD5(订单号+盐)
[0027] invoke String.split("\\.")
[0031] invoke String.equals(...)             ← 校验和比对
[0033] if-eqz v2, +055h                      ← 比对为假→跳失败分支
```

**`wxapi/WXEntryActivity$2.handleMessage`**
```
[0024] const-string "89d43e35dd25de5d2ce9334f2624d6a61345893a"
[0028] invoke Common.md(...)
[0031] invoke String.split("\\.")
[0035] invoke String.equals(...)
[0037] if-eqz v4, +068h
```

**`az$11.handleMessage`（上一轮已确认）**
```
[0075] if (!v3_13.equals(v0_11[0]))   // Dalvik: 比较 + 分支完好
```

此外，`Common.md` 经反编译确认是**标准 MD5→十六进制**（建 hex 表 → `MessageDigest.getInstance("MD5")` → digest → 转 hex），**未被改为恒返回/跳过**。

**结论：整个 DEX 中，没有任何一处对授权校验逻辑的修改。** 校验函数、三个比对分支、盐值引用全部原样保留。

---

## 四、那破解到底「改」了什么？

结合以上铁证，破解版与原版在**授权代码逻辑上无差异**。它之所以能免付费解锁，靠的是**设计层漏洞 + 外部响应伪造**，而非改 APK 逻辑：

1. **致命弱点：盐值明文硬编码在客户端。**
   `89d43e35dd25de5d2ce9334f2624d6a61345893a` 以明文写死在 DEX 里，任何人都能离线算出
   `MD5(任意账号/订单号 + 该盐)`。
2. **「服务端校验和」实为「客户端也能算的校验和」。**
   服务端返回的 `checksum` 段是用同一个盐算的——这意味着**服务器并没有真正的服务端密钥**，校验形同虚设。破解者只需让 App 收到的响应首段等于 `MD5(标识+盐)`，即可被所有分支「合法通过」。
3. **伪造响应的落点不在 App 代码里，而在响应/会话层。**
   由于三个网络回调（`az$4` / `HelloWorldActivity$4` / 微信回调）都只是 `p3.body().string()` 原样转发，**App 代码本身没有被改成注入伪造响应**。可行的伪造途径是外部层：
   - 设备端 hosts/DNS 把 `ideacalc.com` 指向一个「永远返回合法校验和响应」的本地/私有服务；或
   - 透明代理/MITM 改写响应；或
   - 官方服务器已停用/被控，对任一账号返回合法响应。
   以上均**不属于 APK 内的代码补丁**。

4. **APK 内唯一可见的「改动」是重打包特征**（见前篇）：
   - 空身份自签名证书（CN/OU/O 全空、25 年有效期）；
   - 重度混淆（字符串加密 `android.arch.core.R.۟ۧۘۗ(...)`、控制流不透明谓词），用于对抗逆向、掩护上述设计漏洞，而非改变校验逻辑。

---

## 五、关于那张 `e82a5c3724b4cba8` 混淆表（澄清上篇猜测）

- 该表的确是 `DbOperate.addOrUpdateKey/getKey` 操作的授权存储表，列名 `af03…`(key)/`ec64…`(value)。
- 打包库 `assets/ideacalc.db` 内预置的 **18 行**键为 8 字节随机十六进制、值为 32–40 位大写字母数字（第 8 行含 `;` 多段），**与运行时写入的 `buyer_account/expired_time/our_trade_no` 明文键名无任何哈希关系**。
- 因此这 18 行**不是预置授权记录**，而是 App 自带的种子数据（函数库/模板/常量等），与破解机制无关。授权记录用的是明文键名写入同一张表（运行时新增行）。

---

## 六、一句话结论（修订上一轮）

`az` 不是补丁落点——**整个授权校验逻辑在 DEX 里一字未改**（三个比对分支 + `Common.md` 均经字节码核验完好）。破解之所以生效，是因为原版把「服务端校验和」的盐值 `89d43e35dd25de5d2ce9334f2624d6a61345893a` **明文硬编码在客户端**，使校验和可被任何人离线算出；破解者只需在**响应/会话层**伪造一个首段等于 `MD5(标识+盐)` 的响应，即可被 App「合法放行」并把 `isDefaultTheme` 置为已付费。这是一个**信任模型失效（客户端已知盐 = 无服务端密钥）** 导致的设计级破解，APK 内的「改动」仅表现为重打包空证书与混淆，而非逻辑补丁。

> 方法论局限同前：无未破解原版 APK，无法做逐字节 diff；但通过对全部校验入口的字节码核验，已能 100% 确认「无逻辑补丁」这一关键结论。

---

## 附：本篇新增产物
- `longbin_helloworld_HelloWorldActivity_decompiled.java`（主 Activity，含闸门读取点）
- `longbin_helloworld_HelloWorldActivityDOLLAR4_decompiled.java`（主 Activity 授权回调，字节码已核验）
- `longbin_helloworld_wxapi_WXEntryActivityDOLLAR2_decompiled.java`（微信授权回调，字节码已核验）
- `longbin_helloworld_SplashActivity_decompiled.java`（启动闸门）
- `longbin_helloworld_Common_decompiled.java`（含 `md` 标准 MD5）
- `longbin_helloworld_DbOperate_decompiled.java`
- `verify_cmp_result.txt`（三处校验分支的 Dalvik 指令证据）
- `auth_readers_result.txt` / `plain_readers_result.txt`（授权键引用定位）
- `数据库导出`：`e82a5c3724b4cba8` 表 18 行 + 各表结构
