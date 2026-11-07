#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEX 字符串 / 证书 / 可疑行为分析"""
import re, json, logging
logging.disable(logging.WARNING)
from androguard.misc import AnalyzeAPK

APK_PATH = r"D:/0000/apk/计算管家破解版.apk"
OUT = r"D:/0000/apk/analysis/dex_findings.json"

a, d, dx = AnalyzeAPK(APK_PATH)

# ---------- 1. 签名证书 ----------
print("================ 签名证书 (META-INF) ================")
cert_info = {}
try:
    certs = a.get_certificates()
    print(f"证书数量: {len(certs)}")
    for i, c in enumerate(certs):
        subj = c.get_subject()
        iss = c.get_issuer()
        not_before = c.get_notBefore()
        not_after = c.get_notAfter()
        print(f"  证书#{i}:")
        print("    主题:", repr(subj.human_friendly if hasattr(subj,'human_friendly') else subj))
        print("    签发者:", repr(iss.human_friendly if hasattr(iss,'human_friendly') else iss))
        print("    有效期:", not_before, "->", not_after)
        # 判断是否为 Android Debug 证书
        sj = str(subj)
        debug = ("Android Debug" in sj) or ("CN=Android Debug" in sj)
        print("    是否为 Debug 证书:", debug)
        cert_info[f"cert_{i}"] = {"subject": str(subj), "issuer": str(iss),
                                  "not_before": str(not_before), "not_after": str(not_after),
                                  "is_debug": debug}
except Exception as e:
    print("  读取证书失败:", e)
    cert_info["error"] = str(e)

# ---------- 2. 类清单 (检测混淆) ----------
print("\n================ 类清单 / 混淆检测 ================")
classes = sorted(str(c) for c in dx.get_classes())
print(f"总类数: {len(classes)}")
# 单字符/短类名（混淆特征）
obf = [c for c in classes if re.search(r'/[a-z]{1,2};$', c) or re.search(r'/[a-zA-Z]$', c)]
print(f"疑似混淆短类名: {len(obf)}")
for c in obf[:40]:
    print("   ", c)
native_candidates = [c for c in classes if 'Native' in c or 'JNI' in c or 'jni' in c]
print(f"含 native/JNI 关键字类: {len(native_candidates)}")
cert_info["total_classes"] = len(classes)
cert_info["obfuscated_short_classes"] = obf

# ---------- 3. 字符串提取与模式匹配 ----------
print("\n================ DEX 字符串 / 可疑模式 ================")
strings = []
for s in dx.get_strings():
    try:
        v = s.get_value()
    except Exception:
        continue
    if isinstance(v, str):
        strings.append(v)
print(f"字符串总数: {len(strings)}")

patterns = {
    "URL(http/https)": re.compile(r'https?://[^\s"\'<>]+', re.I),
    "IP地址": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b'),
    "发短信/SMS": re.compile(r'(?i)(SmsManager|sendTextMessage|sendMultipartTextMessage|sendDataMessage)'),
    "电话/设备标识": re.compile(r'(?i)(getDeviceId|getSubscriberId|getSimSerialNumber|TelephonyManager|getLine1Number)'),
    "动态加载/执行": re.compile(r'(?i)(DexClassLoader|PathClassLoader|Runtime\.getRuntime|ProcessBuilder|loadLibrary|System\.load)'),
    "反射": re.compile(r'(?i)(Class\.forName|Method.*invoke|getMethod|getDeclaredMethod)'),
    "应用枚举": re.compile(r'(?i)(getInstalledPackages|getInstalledApplications|queryIntentActivities|PackageManager)'),
    "账号/标识": re.compile(r'(?i)(AccountManager|GET_ACCOUNTS|Android_ID|Settings\.Secure\.getString)'),
    "ROOT检测": re.compile(r'(?i)(su\b|Superuser|Magisk|root)'),
    "支付/破解相关": re.compile(r'(?i)(alipay|wxpay|wechat|Weixin|pay|vip|premium|license|licenseKey|verify|sign|purchase|crack|激活|会员|充值|破解|序列号|授权)'),
    "邮件地址": re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
}

hits = {}
for label, pat in patterns.items():
    found = []
    for s in strings:
        if pat.search(s):
            found.append(s.strip())
    # 去重并截断
    seen = list(dict.fromkeys(found))[:60]
    hits[label] = seen
    print(f"\n--- {label}: {len(found)} 命中 (展示前 {len(seen)}) ---")
    for x in seen:
        print("   ", x[:300])

# 进一步：抽取所有 URL 并按 host 聚合
url_hosts = {}
for s in strings:
    for m in patterns["URL(http/https)"].finditer(s):
        u = m.group(0).rstrip(').,;')
        try:
            from urllib.parse import urlparse
            h = urlparse(u).netloc
            url_hosts[h] = url_hosts.get(h, 0) + 1
        except Exception:
            pass
print("\n--- 外联域名(host)聚合 ---")
for h, n in sorted(url_hosts.items(), key=lambda x:-x[1]):
    print(f"   {n:4d}  {h}")

cert_info["url_hosts"] = url_hosts
cert_info["pattern_hits"] = {k: v for k, v in hits.items()}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(cert_info, f, ensure_ascii=False, indent=2)
print("\n[+] DEX 发现已写入:", OUT)
