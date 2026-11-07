# -*- coding: utf-8 -*-
"""注入 PrefBootstrap：启动即把三个付费判定值写成"已购买"状态。

购买成功回调（HelloWorldActivity$x）写入的正是一组：
    isDefaultTheme = true
    font_size     = "24"
    screen_mode   = "landscape"
免费态则是 isDefaultTheme=false / font_size="28" / screen_mode="normal"。
各付费功能入口都同时比对这三个值，因此统一在启动时置为已购买态。
"""
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth_base')
SMALI = os.path.join(ROOT, 'smali')
OUT = os.path.join(SMALI, 'longbin', 'helloworld', 'PrefBootstrap.smali')

BODY = '''.class public final Llongbin/helloworld/PrefBootstrap;
.super Ljava/lang/Object;
.source "PrefBootstrap.java"


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method


.method public static a(Landroid/content/Context;)V
    .locals 3

    invoke-static {p0}, Landroid/preference/PreferenceManager;->getDefaultSharedPreferences(Landroid/content/Context;)Landroid/content/SharedPreferences;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "isDefaultTheme"

    const/4 v2, 0x1

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "font_size"

    const-string v2, "24"

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    const-string v1, "screen_mode"

    const-string v2, "landscape"

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v0

    invoke-interface {v0}, Landroid/content/SharedPreferences$Editor;->commit()Z

    return-void
.end method
'''

CALL = '    invoke-static {p0}, Llongbin/helloworld/PrefBootstrap;->a(Landroid/content/Context;)V\n'

TARGETS = [
    ('SplashActivity.smali',
     '    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V\n'),
    ('HelloWorldActivity.smali',
     '    invoke-super {p0, p1}, Landroid/support/v7/app/AppCompatActivity;->onCreate(Landroid/os/Bundle;)V\n'),
]


def main():
    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        f.write(BODY)
    print('created', os.path.relpath(OUT, ROOT))

    for name, anchor in TARGETS:
        p = os.path.join(SMALI, 'longbin', 'helloworld', name)
        with open(p, encoding='utf-8', errors='ignore') as f:
            s = f.read()
        if 'PrefBootstrap' in s:
            print('skip (already injected):', name)
            continue
        if anchor not in s:
            print('ANCHOR MISS:', name)
            continue
        s = s.replace(anchor, anchor + '\n' + CALL, 1)
        with open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(s)
        print('injected:', name)


if __name__ == '__main__':
    main()
