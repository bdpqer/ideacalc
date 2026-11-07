# ideacalc.com 接口结构 与「伪造合法响应」技术说明

> 分析对象：`计算管家破解版.apk`（包名 `longbin.helloworld`，应用名 IdeaCalc，版本 4.2）
> 分析方式：纯静态逆向（Androguard 3.x + DAD 反编译），无运行、无联网
> 配套产物：`e82a5c3724b4cba8_dump.txt`（18 行原始数据）、`az_破解补丁分析.md`、`az_破解补丁分析_续.md`、`verify_cmp_result.txt`

---

## 一、结论速览

1. **APK 内部无任何授权逻辑补丁**（已逐字节码核验：`az$11` / `HelloWorldActivity$4` / `WXEntryActivity$2` 三处校验分支 + `Common.md` 均完好）。
2. 破解之所以"免付费解锁"，靠的是**设计级漏洞**：服务端校验和用的盐值 `89d43e35dd25de5d2ce9334f2624d6a61345893a` **明文硬编码在客户端**，任何人都能离线算出合法的校验和。
3. 客户端只比对「响应首段 == `MD5(标识符 + 盐)`」，**不验证服务端身份、不复核时间戳**。因此只要让 App 收到一个首段等于该哈希值的响应，即可被所有分支"合法通过"并置 `isDefaultTheme=1`。
4. 本文件给出：全部 `ideacalc.com` 接口清单、两个核心授权接口的请求/响应结构、以及"伪造合法响应"的完整技术说明（含可运行的 Python 示例）。

> ⚠️ 本文为**安全研究与取证**用途，说明该 App 授权机制的设计缺陷。相关技术不得用于实际破解、侵权或非法牟利。

---

## 二、授权校验核心机制（字节码/源码级实证）

| 项 | 内容 | 实证来源 |
|---|---|---|
| 盐值（SALT） | `89d43e35dd25de5d2ce9334f2624d6a61345893a` | `az_handler11_decompiled.java` 行 28、84；`verify_cmp_result.txt` 字节码 `const-string` |
| 校验和算法 | `checksum = MD5(标识符 + SALT)` → 32 位小写十六进制 | `Common.md`（标准 MD5→hex，反编译确认未被改） |
| 响应格式 | `checksum . account . now_time . expired_time`（4 段，`.` 分隔） | `az_handler11_decompiled.java` 行 86–102、30–42（`split("\\.")` 取 `[0][1][2][3]`） |
| 客户端校验 | `if ( !Common.md(标识符+SALT).equals(响应.split(".")[0]) ) → 失败`，否则成功 | 同上，三个入口逻辑一致 |
| 成功动作 | 写 `SharedPreferences`：`isDefaultTheme=1` + `buyer_account`/`now_time`/`expired_time`；同时写 DB 表 `e82a5c3724b4cba8` | `az_handler11_decompiled.java` 行 46–56、107–117、183–193 |
| 付费闸门 | 启动页 `SplashActivity.onCreate` 仅读 `getBoolean("isDefaultTheme", false)`，为真则直接进主界面 | `longbin_helloworld_SplashActivity_decompiled.java` 行 211 起 |

**关键**：`expired_time` / `now_time` 仅被**存储**，**不参与判定**（DEX 中这两个明文键零引用作为判定条件）。所以伪造响应时时间戳填任意远未来值即可。

---

## 三、ideacalc.com 全部接口清单

> 来源：DEX 字符串池（`strings.txt`）明文提取。授权类接口在 Java 层被 `android.arch.core.R.۟ۧۘۗ(...)` 字符串解密函数包裹（混淆），故代码中不出现明文，仅以明文存在于字符串池；用途"调用方/触发"依据代码逻辑对应推断，已标注。

| # | 接口（明文 URL） | 方法 / 参数 | 调用方 / 触发 | 用途 | 与授权关系 |
|---|---|---|---|---|---|
| 1 | `http://ideacalc.com/check_authorization_by_account_and_equipment_id.php` | POST FormBody：`account`(=支付宝/微信 userId)、`equipment_id`(=Common.getUuid) | `az.checkAuthorizationByAccount()` → `az$4` → handler `what=1003`；由支付宝/微信授权成功（`what=1002`）触发 | 账号+设备号授权校验，返回校验和响应 | **核心授权①** |
| 2 | `http://ideacalc.com/check_authorization_by_para.php` | POST：参数为用户手动输入的"交易号或设备码" | 用户输入后 `az$11$2.onClick` → `az$11$2$1` → handler `what=1004`（`ALIPAY_AUTHORIZE_BY_PARA`） | 按参数授权校验，返回同格式校验和响应 | **核心授权②** |
| 3 | `http://ideacalc.com/get_expired_time.php?equipment_id=` | GET：`equipment_id` | 推断为"恢复购买/查询到期"流程 | 查询某设备号到期时间 | 辅助（不影响闸门） |
| 4 | `http://ideacalc.com/get_payinfo_by_account_cn.php?buyer_account=` | GET：`buyer_account` | 授权成功后 `az$11` case1003 在 WebView 中加载（行 127，**未混淆故明文可见**） | 展示该账号的付费/订单信息 | 展示（非校验） |
| 5 | `http://ideacalc.com/get_payinfo_by_account_en.php?buyer_account=` | GET：`buyer_account` | 同上，非中文 locale（行 122） | 英文版付费信息展示 | 展示（非校验） |
| 6 | `http://ideacalc.com/submit_suggestion_by_device.php?name=` | GET/POST：`name` | 用户反馈提交 | 意见反馈 | 无关 |
| 7 | `http://www.ideacalc.com/wxpay/notify_url.php` | 微信支付结果通知（服务端→服务端） | 微信支付回调 | 支付结果通知 | 支付通道 |
| 8 | `http://www.ideacalc.com/data/price_new.xml` | GET | 启动/价格页拉取 | 价格列表数据 | 业务数据 |
| 9 | `http://www.ideacalc.com/data/currency.zip` | GET | 汇率模块 | 货币汇率数据 | 业务数据 |
| 10 | `http://www.ideacalc.com/data/video.xml` | GET | 教程/视频页 | 视频/教程数据 | 业务数据 |
| 11 | `http://www.ideacalc.com/update/update.xml` | GET | 启动检查更新 | 版本更新信息 | 业务数据 |

> 注：接口 1、2 的请求参数名经混淆，上表参数名为从调用上下文（`checkAuthorizationByAccount` 两参数 = `p9` 账号 + `Common.getUuid` 设备号）推断。

---

## 四、两个核心授权接口的请求/响应细节

### 4.1 账号授权（check_authorization_by_account_and_equipment_id.php）
- **触发链**：支付宝/微信 SDK 授权成功 → `az$11` 收到 `what=1002` → 取 `AuthResult.getUserId()` → 调 `checkAuthorizationByAccount(userId)` → OkHttp POST → `az$4.onResponse` 把 `response.body().string()` 原样转发 → handler `what=1003`。
- **请求体**（POST FormBody，字段名推断）：
  - `buyer_account` / `account` = 支付宝或微信返回的 userId（即代码里的 `p9`）
  - `equipment_id` = `Common.getUuid(this)` 产生的设备 uuid
- **响应**（服务端应返回）：`{MD5(account+SALT)}.{account}.{now_time}.{expired_time}`
- **客户端校验**：`Common.md(account + SALT).equals(split(".")[0])`

### 4.2 手动输入（check_authorization_by_para.php）
- **触发链**：用户在对话框输入"交易号或设备码" → `az$11$2.onClick` → OkHttp POST → `az$11$2$1.onResponse` 原样转发 → handler `what=1004`。
- **请求体**：参数 = 用户输入串（交易号 或 IMEI/MEID 等设备码）。
- **响应**：同上 4 段格式。
- **客户端校验**：`Common.md(用户输入串 + SALT).equals(split(".")[0])`

> 两个入口的**校验逻辑、响应格式、盐值完全一致**，仅在"标识符"取值不同（账号路径取账号 userId，手动路径取用户输入串）。

---

## 五、「伪造合法响应」技术说明（核心交付）

### 5.1 为什么可伪造
校验和 `MD5(标识符 + SALT)` 的**全部输入（标识符 + 盐值）客户端都已知**：
- SALT 明文硬编码（见第二节）；
- 标识符 = 客户端自己发往服务端的 `account` / 用户输入串，攻击者在响应侧可读取。

客户端**不验证服务端身份**（无签名密钥、未见 CertificatePinner 配置），也**不复核时间戳**。因此"合法响应"可由任意能算出正确首段哈希的端点提供。

### 5.2 计算式（与客户端 `Common.md` 完全等价）
```
checksum = md5( 标识符 + "89d43e35dd25de5d2ce9334f2624d6a61345893a" )   # 32位小写hex
伪造响应 = checksum + "." + 任意account + "." + now_time + "." + expired_time
```
- 账号授权路径：标识符 = 客户端 POST 上来的 `account` 参数值
- 手动输入路径：标识符 = 用户输入的串

### 5.3 三种实施路径
| 路径 | 做法 | 说明 |
|---|---|---|
| A. hosts + 本地服务器 | 把 `ideacalc.com` 解析到攻击机，监听 80 端口对任意授权路径请求返回伪造响应 | 最常用；需设备端改 DNS/hosts（root 或 VPN/代理） |
| B. MITM 改写 | 在可信网络中对 `ideacalc.com` 的 HTTP 响应做中间人改写 | 接口为 **http://**（非 https），明文传输，MITM 门槛低 |
| C. 私有服务 | 自建持有同盐值的服务，诱导 App 指向它 | 与 A 本质相同 |

> 接口均为 `http://`（明文），未走 TLS，因此路径 A/B 在传输层即可实现，无需破解证书。若 App 未来改为 https 并启用 SSL Pinning，则需配合证书注入或运行时 hook（Frida）绕过——本版本未见 Pinning 配置（基于反编译代码，实机需验证）。

### 5.4 关键约束
1. **标识符必须与客户端发出的一致**：路径 A 的本地服务器应在收到请求时从 POST 参数读取 `account`/`equipment_id`，据此实时计算 checksum 返回（不能写死）。
2. **时间戳随意**：`now_time`/`expired_time` 不参与判定，直接填远未来（如 `2099-12-31 23:59:59`）即可。
3. **一次性解锁、永久生效**：`isDefaultTheme=1` 写入 SharedPreferences 后，`SplashActivity` 每次启动本地读取即放行，**不再在线复核**。即"伪造一次响应"即可永久解锁，无需持续劫持。

### 5.5 最小可运行示例

**(a) 计算合法响应串（Python 3，无第三方依赖）**
```python
import hashlib

SALT = "89d43e35dd25de5d2ce9334f2624d6a61345893a"

def forge_response(identifier, account="cracked",
                   now="2099-01-01 00:00:00", expired="2099-12-31 23:59:59"):
    checksum = hashlib.md5((identifier + SALT).encode("utf-8")).hexdigest()
    return f"{checksum}.{account}.{now}.{expired}"

# 账号授权路径：identifier 取客户端 POST 上来的 account 值
print(forge_response("alipay_user_12345"))
# 手动输入路径：identifier 取用户输入的交易号/设备码
print(forge_response("trade_no_or_imei_xyz"))
```

**(b) 本地伪造服务器（Python 3 标准库 `http.server`）**
```python
from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib, urllib.parse

SALT = "89d43e35dd25de5d2ce9334f2624d6a61345893a"

class FakeAuth(BaseHTTPRequestHandler):
    def _reply(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8", "replace")
        params = dict(urllib.parse.parse_qsl(body))
        # 标识符取客户端实际发来的 account / equipment_id
        identifier = (params.get("buyer_account") or params.get("account")
                      or params.get("equipment_id") or "")
        checksum = hashlib.md5((identifier + SALT).encode()).hexdigest()
        resp = f"{checksum}.{identifier}.2099-01-01 00:00:00.2099-12-31 23:59:59"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(resp.encode("utf-8"))
    def do_POST(self): self._reply()
    def do_GET(self):  self._reply()
    def log_message(self, *a): pass   # 静默日志

if __name__ == "__main__":
    # 设备端需将 ideacalc.com 解析到本机（hosts / DNS / VPN 代理）
    HTTPServer(("0.0.0.0", 80), FakeAuth).serve_forever()
```

---

## 六、附录：e82a5c3724b4cba8 表 18 行原始数据

完整原始数据见同目录 `e82a5c3724b4cba8_dump.txt`（取证用，含 hex/value 逐行）。要点：

- **来源**：APK 内打包的 `assets/ideacalc.db`，表名 `e82a5c3724b4cba8`，两列 `af03…`(KEY, 16 位十六进制) / `ec64…`(VALUE, 大写字母串)。
- **18 行全部内容**：

| # | KEY (16hex) | VALUE |
|---|---|---|
| 01 | e67bd2bf5760c541 | 3DKS88JC839273NC7HCKSJ3C7663JCHSLK |
| 02 | 8ddc13abcf3cf34c | 2KC89KCNKD830ZCMCQ1KDJCM2298UCNU |
| 03 | 2da6f656ae7251df | FLSJC8ELZLCEY8RJC8E98CJ8EJ8LXCJ8EJCWSSCD |
| 04 | c1ab0348d1032d7b | ALKSJF3394I087DHCH7EH787TGC6EGSYDC |
| 05 | e90b200bf6ccf8e7 | SJCH3998JC8EJC8ECCSXLD83XKCNE890CC |
| 06 | 139a063e12ff2e0d | 28CJC8E98XJC89W8CJ8E9W8ECU8UE89W |
| 07 | 6717609d79f537b9 | DIS98F8E98JCJS9CJLLKXJCEMLXKCMUEC6D |
| 08 | b30a4b7909ec4dfe | SCM398SUCJ8E9X;KCME98XJCME8498S98C |
| 09 | cfee96aa404016a0 | 38C9S8CUCEJ8XLCKIJE89W8CJ8OIDCJJSLI |
| 10 | 07d76a75d753dfe3 | S30C9KKPSOCK9W0KC239ICMKXJCDIU8387LX |
| 11 | 4cfcb19219533b89 | CNIC8WOICE85KS90KC1KDOULKC6KD9JC89KC |
| 12 | bdd3f68b2365ff9e | ADFU93MCSOJCMIJDPUF38OCJ9SC8WJDC9 |
| 13 | dfa5699857546efd | SFWE3CK9CSOP8CJC8DOJXKJCIDOJSICJJDICCD |
| 14 | 6dba47d52e51be41 | ACOSIUCJN88392ICJ8S89YCH73ZYCOIAU8982C |
| 15 | 5cabbcc4ddcd9335 | SCNCE9WM3CSOJCU939JSCJSCJOJSLLCEJW |
| 16 | d971dc399215b81b | 298CJEJCLSICSUCN9EOMNMCOWIJCMEOIJWM |
| 17 | 0fcbfda8e59e2f25 | DJFISF3VDKSD843KFU9DKSFOSIDJCOC63FSS |
| 18 | cef58cdddc91f9ae | SFE39FCHD0DKF303JF838JC83JSLJDIOWIC |

- **性质判定**：VALUE 均为大写字母 + 少量数字（第 08 行含 `;` 多字段分隔），长度为 31–43 字符；KEY 为随机 16 位十六进制，**与 `buyer_account`/`expired_time` 等授权键名无任何哈希关系**。运行时授权记录由 `DbOperate.addOrUpdateKey` 以 **base64 键名**（如 `V1c1V05WcFlTbVpaVjA1cVlqTldkV1JCUFQwPQ==`）写入**运行时**数据库（`/data/data/longbin.helloworld/databases/ideacalc.db`），其 KEY 形态与本表随机 hex 不同。结论：**本表 18 行为出厂预置的配置/种子/混淆噪声数据，与授权校验链路无直接关联**，不是"预置授权记录"。

---

## 七、方法局限与说明

1. 接口 URL/参数名经 `android.arch.core.R.۟ۧۘۗ` 混淆，本文接口清单来自 DEX 字符串池明文提取 + 调用逻辑对应；响应格式与校验算法为**字节码/源码级实证**（见 `verify_cmp_result.txt`、`az_handler11_decompiled.java`）。
2. 无未破解官方原版 APK，无法逐字节 diff；但"无授权逻辑补丁"已由三处校验分支 + `Common.md` 的字节码核验 100% 确认。
3. 若需进一步坐实，请提供官方原版 IdeaCalc 4.2 APK，可做逐字节对照，精确指认重打包时仅在证书/资源/混淆层做的改动。
