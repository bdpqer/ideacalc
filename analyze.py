#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计算管家破解版.apk 静态分析脚本 (基于 Androguard, 纯 Python)"""
import sys, re, json, logging
logging.disable(logging.WARNING)  # 丢弃 DEBUG/INFO 噪音
from androguard.misc import AnalyzeAPK
from androguard.core.api_specific_resources import load_permissions

# 兜底的危险权限集合（标准 Android dangerous 列表）
FALLBACK_DANGEROUS = {
 "android.permission.READ_CALENDAR","android.permission.WRITE_CALENDAR",
 "android.permission.CAMERA",
 "android.permission.READ_CONTACTS","android.permission.WRITE_CONTACTS","android.permission.GET_ACCOUNTS",
 "android.permission.ACCESS_FINE_LOCATION","android.permission.ACCESS_COARSE_LOCATION",
 "android.permission.RECORD_AUDIO",
 "android.permission.READ_PHONE_STATE","android.permission.READ_PHONE_NUMBERS","android.permission.CALL_PHONE",
 "android.permission.READ_CALL_LOG","android.permission.WRITE_CALL_LOG","android.permission.ADD_VOICEMAIL",
 "android.permission.USE_SIP","android.permission.PROCESS_OUTGOING_CALLS","android.permission.ANSWER_PHONE_CALLS",
 "android.permission.ACCEPT_HANDOVER",
 "android.permission.BODY_SENSORS","android.permission.BODY_SENSORS_BACKGROUND",
 "android.permission.SEND_SMS","android.permission.RECEIVE_SMS","android.permission.READ_SMS",
 "android.permission.RECEIVE_WAP_PUSH","android.permission.RECEIVE_MMS","android.permission.READ_CELL_BROADCASTS",
 "android.permission.READ_EXTERNAL_STORAGE","android.permission.WRITE_EXTERNAL_STORAGE",
 "android.permission.READ_MEDIA_IMAGES","android.permission.READ_MEDIA_VIDEO","android.permission.READ_MEDIA_AUDIO",
 "android.permission.ACCESS_BACKGROUND_LOCATION",
 "android.permission.POST_NOTIFICATIONS","android.permission.NEARBY_WIFI_DEVICES",
}
def get_dangerous(target_sdk):
    try:
        mapping = load_permissions(int(target_sdk) if target_sdk else 28)
        return {p for p, meta in mapping.items()
                if isinstance(meta, dict) and "dangerous" in str(meta.get("protectionLevel","")).lower()}
    except Exception:
        return FALLBACK_DANGEROUS

APK_PATH = r"D:/0000/apk/计算管家破解版.apk"
OUT = r"D:/0000/apk/analysis/report_data.json"

print("[*] 正在加载 APK (首次解析可能稍慢) ...")
a, d, dx = AnalyzeAPK(APK_PATH)
print("[*] 加载完成.\n")

report = {}

# ---- 基本信息 ----
print("================ 基本信息 ================")
print("包名 (package):", a.get_package())
print("应用名 (app_name):", a.get_app_name())
print("版本名:", a.get_androidversion_name(), "| 版本号:", a.get_androidversion_code())
print("Min SDK:", a.get_min_sdk_version(), "| Target SDK:", a.get_target_sdk_version())
print("主 Activity:", a.get_main_activity())
try:
    dbg = a.get_attribute_value("debuggable", "application")
except Exception:
    dbg = None
print("是否 debuggable:", dbg)
report["package"] = a.get_package()
report["app_name"] = a.get_app_name()
report["version_name"] = a.get_androidversion_name()
report["version_code"] = a.get_androidversion_code()
report["min_sdk"] = a.get_min_sdk_version()
report["target_sdk"] = a.get_target_sdk_version()
report["main_activity"] = a.get_main_activity()
report["debuggable"] = dbg

# ---- 权限 ----
print("\n================ 权限 (Permissions) ================")
perms = a.get_permissions()
dangerous = set(p for p in perms if p in get_dangerous(a.get_target_sdk_version()))
print(f"共 {len(perms)} 条权限, 其中危险权限 {len(dangerous)} 条:\n")
report["permissions"] = sorted(perms)
report["dangerous_permissions"] = sorted(dangerous)
for p in sorted(perms):
    tag = "  [危险]" if p in dangerous else ""
    print(" -", p, tag)

# ---- 组件 ----
print("\n================ 组件 (Components) ================")
def show(title, items):
    print(f"\n--- {title}: {len(items)} ---")
    for it in items:
        print("  ", it)
report["activities"] = a.get_activities()
report["services"] = a.get_services()
report["receivers"] = a.get_receivers()
report["providers"] = a.get_providers()
show("Activities", report["activities"])
show("Services", report["services"])
show("Receivers", report["receivers"])
show("Providers", report["providers"])

# 导出组件 (可被外部启动) 检测
exported = {"activities":[], "services":[], "receivers":[], "providers":[]}
for tag, getter in [("activities", a.get_activities),
                    ("services", a.get_services),
                    ("receivers", a.get_receivers),
                    ("providers", a.get_providers)]:
    for comp in getter():
        try:
            if a.is_exported(comp):
                exported[tag].append(comp)
        except Exception:
            pass
report["exported_components"] = exported
print("\n[导出/可被外部启动的组件]")
for k,v in exported.items():
    if v:
        print(f"  {k}: {len(v)}")
        for c in v: print("    -", c)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("\n[+] 基础信息已写入:", OUT)
