# -*- coding: utf-8 -*-
"""计算管家 4.4.3 —— v4 构建脚本（基线：已去授权/去更新的成品反编译目录 work/v4）

v4 相对 v3 的两处改动：
  1) PrefBootstrap 改为「先读后比，只有三值不一致才写」，写入用 apply() 异步提交，
     避免每次 onResume 都同步 commit、且不会覆盖用户之后修改的显示设置。
  2) 付费闸门不再用正则模式盲替换，改为「解析目标标签块、只对纯提示块（AlertDialog/Toast）
     的 if-eqz 做 nop」，其余一律保留原判定并打印出来。

另外沿用 v3 的两处上下文修正：
  - HelloWorldActivity.C() 版本迁移常量 "26"/"normal" -> "24"/"landscape"
  - SplashActivity / HelloWorldActivity 的 onResume 注入 PrefBootstrap（range 形式，兼容 p 寄存器）
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v4')
SMALI = os.path.join(ROOT, 'smali')

PREF_BOOTSTRAP = '''.class public final Llongbin/helloworld/PrefBootstrap;
.super Ljava/lang/Object;
.source "PrefBootstrap.java"


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method

.method public static a(Landroid/content/Context;)V
    .locals 9

    invoke-static {p0}, Landroid/preference/PreferenceManager;->getDefaultSharedPreferences(Landroid/content/Context;)Landroid/content/SharedPreferences;

    move-result-object v0

    const-string v1, "isDefaultTheme"

    const/4 v2, 0x0

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z

    move-result v3

    const-string v1, "font_size"

    const-string v2, "28"

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v4

    const-string v1, "screen_mode"

    const-string v2, "normal"

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getString(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v5

    const/4 v6, 0x0

    if-nez v3, :fb_font

    const/4 v6, 0x1

    :fb_font
    const-string v1, "24"

    invoke-virtual {v1, v4}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v8

    if-nez v8, :fb_screen

    const/4 v6, 0x1

    :fb_screen
    const-string v1, "landscape"

    invoke-virtual {v1, v5}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v8

    if-nez v8, :fb_check

    const/4 v6, 0x1

    :fb_check
    if-eqz v6, :fb_return

    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v7

    const-string v1, "isDefaultTheme"

    const/4 v2, 0x1

    invoke-interface {v7, v1, v2}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;

    move-result-object v7

    const-string v1, "font_size"

    const-string v2, "24"

    invoke-interface {v7, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v7

    const-string v1, "screen_mode"

    const-string v2, "landscape"

    invoke-interface {v7, v1, v2}, Landroid/content/SharedPreferences$Editor;->putString(Ljava/lang/String;Ljava/lang/String;)Landroid/content/SharedPreferences$Editor;

    move-result-object v7

    invoke-interface {v7}, Landroid/content/SharedPreferences$Editor;->apply()V

    :fb_return
    return-void
.end method
'''

CAND = re.compile(
    r'(?m)^(    const-string ([vp]\d+), ("landscape"|"24")\n)\n'
    r'(    invoke-virtual \{(?:[vp]\d+), \2\}, Ljava/lang/String;->equals\(Ljava/lang/Object;\)Z\n)\n'
    r'(    move-result ([vp]\d+)\n)\n'
    r'(    if-eqz \6, (:\S+)\n)\n')


def read(p):
    with open(p, encoding='utf-8', errors='ignore') as f:
        return f.read()


def write(p, s):
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


def block_of(body, label):
    """取标签块（到下一个标签为止）"""
    lines = body.split('\n')
    out = []
    started = False
    for l in lines:
        st = l.strip()
        if not started:
            if st == label:
                started = True
            continue
        if st.startswith(':'):
            if st.startswith(':try_start') or st.startswith(':try_end') or st.startswith(':catch'):
                continue
            break
        if st:
            out.append(st)
    return out


def is_prompt_block(ops):
    """目标块是否属于「免费侧反制」：提示框 / 跳转付费页 / 隐藏付费控件。

    其它块（findViewById 布局初始化、return 返回值、setVisibility 显示等）一律不动，
    避免把正常逻辑一并短路（v3 的纯正则替换在 HelloWorldActivity$f2/$j1 等块上就改错了）。
    """
    text = '\n'.join(ops)
    if 'startActivity' in text and 'Llongbin/helloworld/az;' in text:
        return True
    if 'Landroid/app/AlertDialog$Builder;' in text or 'Landroid/widget/Toast;->makeText' in text:
        if 'putBoolean' not in text:
            return True
    if 'setVisibility' in text and re.search(r'const/16 [vp]\d+, 0x8', text) and 'findViewById' not in text:
        return True
    return False


def patch_gates():
    changed = files = 0
    kept = []
    for dp, _, ns in os.walk(SMALI):
        for fn in ns:
            if not fn.endswith('.smali'):
                continue
            p = os.path.join(dp, fn)
            s = read(p)
            if '"landscape"' not in s or '"24"' not in s:
                continue
            hits = list(CAND.finditer(s))
            if not hits:
                continue
            # 只处理同文件内 landscape 与 "24" 成对的付费判定块
            if not ({'landscape', '24'} <= {m.group(3).strip('"') for m in hits}):
                continue
            edits = []
            for m in hits:
                line_no = s[:m.start(7)].count('\n') + 1
                body_start = s.rfind('.method', 0, m.start(7))
                body_end = s.find('.end method', m.start(7))
                body = s[body_start:body_end]
                ops = block_of(body, m.group(8))
                if is_prompt_block(ops):
                    edits.append((m.start(7), m.end(7)))
                else:
                    kept.append((os.path.relpath(p, SMALI), line_no, m.group(8),
                                 ops[0][:70] if ops else '(空块/未解析)'))
            if not edits:
                continue
            for a, b in sorted(edits, reverse=True):
                s = s[:a] + '    nop\n' + s[b:]
            write(p, s)
            files += 1
            changed += len(edits)
    print('[2] 闸门 nop 化（仅纯提示块）: %d 文件 / %d 处' % (files, changed))
    if kept:
        print('    保留未改的判定 %d 处（目标块非纯提示块）：' % len(kept))
        for f, ln, lb, first in kept[:12]:
            print('      %s:%d %s -> %s' % (f, ln, lb, first))
    return changed


def patch_version_migration():
    p = os.path.join(SMALI, 'longbin', 'helloworld', 'HelloWorldActivity.smali')
    s = read(p)
    m = re.search(r'\.method private C\(\)V(.*?)\.end method', s, re.S)
    if not m:
        print('[3] ANCHOR MISS: C()')
        return
    body = m.group(1)
    n = 0
    for old, new in [('const-string v7, "26"', 'const-string v7, "24"'),
                     ('const-string v7, "normal"', 'const-string v7, "landscape"')]:
        if old in body:
            body = body.replace(old, new, 1)
            n += 1
    if n:
        s = s[:m.start(1)] + body + s[m.end(1):]
        write(p, s)
    print('[3] C() 迁移常量改为已购买态: %d 处' % n)


CALL = ('    invoke-static/range {p0 .. p0}, '
        'Llongbin/helloworld/PrefBootstrap;->a(Landroid/content/Context;)V\n')


def inject_onresume(name, sig):
    p = os.path.join(SMALI, 'longbin', 'helloworld', name)
    s = read(p)
    m = re.search(r'(?m)^' + re.escape(sig) + r'\n    \.locals (\d+)\n', s)
    if not m:
        print('[4] ANCHOR MISS:', name)
        return False
    end = m.end()
    if 'PrefBootstrap' in s[end:end + 200]:
        print('[4] skip (already injected):', name)
        return True
    s = s[:end] + '\n' + CALL + s[end:]
    write(p, s)
    print('[4] 注入 onResume:', name)
    return True


def install_pref_bootstrap():
    p = os.path.join(SMALI, 'longbin', 'helloworld', 'PrefBootstrap.smali')
    write(p, PREF_BOOTSTRAP)
    print('[1] PrefBootstrap 改写为「先读后比 + apply()」')


def verify():
    fb = read(os.path.join(SMALI, 'longbin', 'helloworld', 'PrefBootstrap.smali'))
    ok = ('apply()V' in fb and 'commit()Z' not in fb and 'getBoolean' in fb
          and 'getString' in fb)
    left = 0
    for dp, _, ns in os.walk(SMALI):
        for fn in ns:
            if fn.endswith('.smali'):
                s = read(os.path.join(dp, fn))
                if '"landscape"' in s and '"24"' in s:
                    left += len(CAND.findall(s))
    print('[verify] PrefBootstrap 幂等+apply: %s | 残留纯提示闸门候选: %d' % (ok, left))
    for name, sig in [('SplashActivity.smali', '.method protected onResume()V'),
                      ('HelloWorldActivity.smali', '.method public onResume()V')]:
        s = read(os.path.join(SMALI, 'longbin', 'helloworld', name))
        print('[verify] %s PrefBootstrap 调用数: %d' % (name, s.count('PrefBootstrap')))
    return ok


def main():
    install_pref_bootstrap()
    patch_gates()
    patch_version_migration()
    inject_onresume('SplashActivity.smali', '.method protected onResume()V')
    inject_onresume('HelloWorldActivity.smali', '.method public onResume()V')
    if not verify():
        sys.exit(1)


if __name__ == '__main__':
    main()
