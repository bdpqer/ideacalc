# `longbin.helloworld.az` 混淆类 · 破解补丁逆向分析

> 工具：Androguard 3.x（纯 Python）+ 内置 DAD Dalvik 反编译器（`DecompilerDAD`）。  
> 方法：定位 `az` 类 → 反编译 `az` 及其内部类 `az$4/az$5/az$11/handler` 与 `DbOperate` → 读取 `handleMessage` 的 Dalvik 字节码确认校验分支。  
> 说明：本环境无 JDK，无法用 jadx，故用 Androguard 的纯 Python 反编译器完成。

---

## 一、`az` 到底是什么

`longbin.helloworld.az` 是应用 **IdeaCalc（计算管家）的「付费 / 授权」Activity**（`extends android.app.TabActivity`），共 23 个方法、20 个字段，内部类包括：

- `az$4`（okhttp3.Callback）—— 授权网络请求的回调
- `az$5`（Thread）—— 拉取价格信息
- **`az$11`（Handler）—— 处理授权结果消息（核心）**
- `az$ButtonAuthorizeListener` / `az$ButtonPayListener` —— 授权/支付按钮

关键方法：`checkAuthorizationByAccount()`（发起授权校验）、`authV2()`（微信授权 V2）、`pay()`（支付宝下单）、`getPriceInfo()`、`onNewIntent()`（微信支付回跳）。

---

## 二、原版授权机制（已从代码完整还原）

授权是**服务端 + 客户端校验和**模式：

1. 用户点「授权」→ `checkAuthorizationByAccount(account)` 用 OkHttp **POST 到**
   `http://ideacalc.com/check_authorization_by_account_and_equipment_id.php`
   参数：`account`（账号）、`equipment_id`（设备 UUID）。
2. 服务端返回形如 `校验和.账号.到期时间.订单号` 的字符串（以 `.` 分割）。
3. `az$4.onResponse` 把服务端响应原样塞进 `Message(what=1003)` 交给 `az$11` 这个 Handler。
4. **Handler 的校验逻辑（`az$11.handleMessage`，case 1003）：**
   ```java
   String account = msg.getData().getString("buyer_account");
   String resp    = msg.getData().getString("response");
   // 客户端硬编码盐值！
   String checksum = Common.md(account + "89d43e35dd25de5d2ce9334f2624d6a61345893a");
   String[] parts  = resp.split("\\.");
   if (!checksum.equals(parts[0])) {        // ← 校验和比对
       // 不匹配 → 弹「请输入支付宝交易号或设备码」对话框（要求真实付费凭证）
   } else {
       // 匹配 → 授权成功
       if (!TextUtils.isEmpty(parts[3]) || !TextUtils.isEmpty(parts[2])) {
           SharedPreferences.Editor e = ...edit();
           e.putBoolean(decode3("WVZoT1JWcFhXbWhrVjNnd1ZrZG9iR0pYVlQwPQ=="), 1);  // 标记为已授权
           e.putString("buyer_account",  parts[1]);
           e.putString("expired_time",   parts[3]);   // 到期时间
           e.putString("our_trade_no",   parts[2]);
           e.commit();
           // 同时写入混淆数据库表 e82a5c3724b4cba8
           DbOperate.addOrUpdateKey("buyer_account", parts[1]);
           DbOperate.addOrUpdateKey("expired_time",   parts[3]);
           DbOperate.addOrUpdateKey("our_trade_no",   parts[2]);
       }
   }
   ```
   解码后的 SharedPreferences 键名：`buyer_account`、`expired_time`、`now_time`、`local_expired_time`、`our_trade_no`、`isDefaultTheme`(置 1)。

5. 校验和算法 `Common.md(x)` 是标准 **MD5(x)→十六进制串**，盐值 `89d43e35dd25de5d2ce9334f2624d6a61345893a` 是**明文硬编码在 APK 里**的。

---

## 三、破解补丁到底改了什么（核心结论）

### 关键事实
对 `az$11.handleMessage` 的 Dalvik 字节码逐行核对，**那个校验和分支 `if (!v3_13.equals(v0_11[0]))` 在第 75 行完好存在、逻辑未删**。也就是说：

> **破解版并没有「删掉 / NOP 掉」`az` 里的授权校验。**

### 这意味着破解必然发生在「响应来源」层
既然 Handler 的校验门还在，要让他「认为已授权」，就必须喂给它一个**能通过 MD5 校验**的响应。而由于校验盐值 `89d43e35dd25de5d2ce9334f2624d6a61345893a` 就写在本 APK 里，破解者可以在**设备上本地重算** `MD5(account + salt)`，无需服务器配合。

因此补丁最可能的落点（按可能性排序）：

1. **响应注入（`checkAuthorizationByAccount` → `az$4.onResponse` 链路）**：破解版把网络回调改成了「忽略真实服务器返回，本地拼出 `MD5(account+salt).account.<订单>.<超远期到期时间>` 直接喂给 Handler」。这样 Handler 的校验门被「合法地」通过——因为它算出的校验和确实等于自己拼的校验和。
2. **伪造/预置账号**：在 `e82a5c3724b4cba8` 这张混淆表里**预置了可用的授权记录**（见下文），启动时由某处读取即视为已授权，根本不走网络。
3. **改 `Common.md` 返回值**（较少见）：让 MD5 函数恒等于服务器首段。

> 为什么是 (1) 或 (2) 而非「删校验」：删校验会留下更明显的代码空洞，而「用硬编码盐本地算出一个合法响应」能在**不改 Handler 逻辑**的前提下完成绕过，更隐蔽——这与本样本中「Handler 校验门完好」的现象完全吻合。

---

## 四、佐证（破解/重打包痕迹）

1. **空身份自签名证书**（前一份报告已确认）：`CN=, OU=, O=, …` 全空、有效期 25 年 → 被重打包工具重新签名，非原作者 Long Bin 原密钥。
2. **重度代码混淆**：
   - **字符串加密**：代码里大量 `android.arch.core.R.۟ۧۘۗ(...)` 调用（那个带阿拉伯语 Unicode 字符的 `۟ۧۘۗ` 是被劫持的字符串解密函数），所有敏感字符串（URL、键名、提示文案）都是 XOR/base64 密文，运行时还原。
   - **控制流混淆（不透明谓词）**：`getPriceInfo()` 等方法中全是 `while(true) switch(魔数)` 的垃圾控制流（如 `-619817969 ^ 28008`），专门对抗人类/工具阅读。
3. **混淆数据库表 `e82a5c3724b4cba8`**：`assets/ideacalc.db` 里这张表表名与列名都是随机 16/32 位十六进制，预置 **18 行** 随机字符串键值对（如 `e67bd2bf5760c541 → 3DKS88JC839273NC7HCKSJ3C7663JCHSLK`）。`DbOperate.addOrUpdateKey` 正是往这张表写授权数据，`getKey()` 从这张表读。这 18 行极可能是破解者**预置的授权种子 / 可用账号记录**（键名以十六进制形式存储，可能是写入前做了哈希/编码）。

---

## 五、方法学局限（务必说明）

- 本环境**没有原版（Google Play 上的 IdeaCalc 4.2, 包名同 `longbin.helloworld`）APK 可供逐字节 diff**。因此我能**100% 确认机制与校验门位置**，并能**高置信度推断补丁落点（响应/网络层 + 本地可算校验和）**，但无法像「改了第 N 条指令」那样逐字节指认——那需要与未破解原版对照。
- 反编译产物（可复现）：`az_decompiled.java`、`az_callbacks_decompiled.java`、`az_handler_decompiled.java`、`az_handler11_decompiled.java`、`handleMessage_disasm.txt`。

---

## 六、一句话总结

`az` 是计算管家的付费授权页，原版用「服务端返回 `MD5(账号+盐).账号.到期.订单` + 客户端校验」来防破解；**破解版没有删掉这个校验门（代码里还在），而是利用盐值明文写在客户端这一致命弱点，在响应/网络层注入一个「本地算出来的合法校验和」响应（和/或预置 `e82a5c3724b4cba8` 授权记录），从而让校验门被「合法通过」、免付费解锁全部功能。** 整个样本还被字符串加密 + 控制流混淆 + 空证书重打包包裹，是典型的「重打包破解」作品。
