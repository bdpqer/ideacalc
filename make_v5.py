# -*- coding: utf-8 -*-
"""计算管家 4.4.3 —— v5 构建脚本（基线：去授权/去更新成品反编译 work/v5）

v5 目标（相对 v4 的三点收敛）：
  A. 付费判定与显示设置解耦：把 44 处 equals("landscape")/equals("24") 的结果直接置为 true
     （invoke+move-result -> const/4 vY,0x1 + nop，等长替换），判定不再读取 font_size / screen_mode。
  B. 补齐布尔字段闸门：iget-boolean ->c:Z + if-eqz，且目标块是付费提示框 -> nop。
  C. PrefBootstrap 只维护 isDefaultTheme，绝不写 font_size / screen_mode；
     C() 版本迁移里的三处写盘（font_size/screen_mode/isDefaultTheme）改为 nop，升级不再覆盖用户设置。
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v5')
SMALI = os.path.join(ROOT, 'smali')
HW = os.path.join(SMALI, 'longbin', 'helloworld')

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
    .locals 5

    invoke-static {p0}, Landroid/preference/PreferenceManager;->getDefaultSharedPreferences(Landroid/content/Context;)Landroid/content/SharedPreferences;

    move-result-object v0

    const-string v1, "isDefaultTheme"

    const/4 v2, 0x0

    invoke-interface {v0, v1, v2}, Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z

    move-result v3

    if-nez v3, :fb_done

    invoke-interface {v0}, Landroid/content/SharedPreferences;->edit()Landroid/content/SharedPreferences$Editor;

    move-result-object v4

    const-string v1, "isDefaultTheme"

    const/4 v2, 0x1

    invoke-interface {v4, v1, v2}, Landroid/content/SharedPreferences$Editor;->putBoolean(Ljava/lang/String;Z)Landroid/content/SharedPreferences$Editor;

    move-result-object v4

    invoke-interface {v4}, Landroid/content/SharedPreferences$Editor;->apply()V

    :fb_done
    return-void
.end method
'''

# const-string 与 invoke 之间允许夹一行 const/…；结果寄存器用 \3 捕获
EQ = re.compile(
    r'(?m)^(    const-string ([vp]\d+), ("landscape"|"24")\n)'
    r'(?:(\n)?(    const(?:/4|/16)? [vp]\d+, 0x[0-9a-f]+\n)|\n)?'
    r'(    invoke-virtual \{([vp]\d+), \2\}, Ljava/lang/String;->equals\(Ljava/lang/Object;\)Z\n)'
    r'(?:(\n)|)'
    r'(    move-result ([vp]\d+)\n)'
)


def read(p):
    with open(p, encoding='utf-8', errors='ignore') as f:
        return f.read()


def write(p, s):
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(s)


def const_one(reg):
    m = re.match(r'v(\d+)$', reg)
    if m and int(m.group(1)) <= 15:
        return '    const/4 %s, 0x1\n' % reg
    return '    const/16 %s, 0x1\n' % reg


def block_of(body, label):
    out, started = [], False
    for l in body.split('\n'):
        st = l.strip()
        if not started:
            if st == label:
                started = True
            continue
        if st.startswith(':'):
            if st.startswith((':try_start', ':try_end', ':catch')):
                continue
            break
        if st:
            out.append(st)
    return out


def force_equals_true():
    files = 0
    sites = 0
    for dp, _, ns in os.walk(SMALI):
        for fn in ns:
            if not fn.endswith('.smali'):
                continue
            p = os.path.join(dp, fn)
            s = read(p)
            if '"landscape"' not in s or '"24"' not in s:
                continue
            # 只处理同文件内两字面量成对的付费判定
            if not re.search(r'const-string [vp]\d+, "landscape"', s):
                continue
            if not re.search(r'const-string [vp]\d+, "24"', s):
                continue
            hits = list(EQ.finditer(s))
            if not hits:
                continue
            edits = []
            for m in hits:
                edits.append((m.start(6), m.end(9), m.group(10)))
            for a, b, reg in sorted(edits, reverse=True):
                s = s[:a] + const_one(reg) + '    nop\n' + s[b:]
            write(p, s)
            files += 1
            sites += len(edits)
    print('[A] equals 判定强制为 true: %d 文件 / %d 处' % (files, sites))
    return sites


IGET = re.compile(r'(?m)^    iget-boolean ([vp]\d+), p0, Llongbin/helloworld/[^\n]+->(\w+):Z$')
IFEQZ = re.compile(r'(?m)^    if-eqz ([vp]\d+), (:\S+)$')


def force_bool_gates():
    files = sites = 0
    for dp, _, ns in os.walk(SMALI):
        for fn in ns:
            if not fn.endswith('.smali'):
                continue
            p = os.path.join(dp, fn)
            s = read(p)
            if 'iget-boolean' not in s or 'if-eqz' not in s:
                continue
            lines = s.split('\n')
            edits = []
            for i, l in enumerate(lines):
                mi = IGET.match(l)
                if not mi:
                    continue
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j >= len(lines):
                    continue
                mf = IFEQZ.match(lines[j])
                if not mf or mf.group(1) != mi.group(1):
                    continue
                ms = s.rfind('.method', 0, sum(len(x) + 1 for x in lines[:i]))
                me = s.find('.end method', sum(len(x) + 1 for x in lines[:i]))
                if ms < 0 or me < 0:
                    continue
                ops = '\n'.join(block_of(s[ms:me], mf.group(2)))
                if ('Landroid/app/AlertDialog$Builder;' in ops
                        or 'Landroid/widget/Toast;->makeText' in ops):
                    edits.append(j)
            if not edits:
                continue
            for j in sorted(edits, reverse=True):
                lines[j] = '    nop'
            write(p, '\n'.join(lines))
            files += 1
            sites += len(edits)
    print('[B] 布尔字段型提示闸门 nop 化: %d 文件 / %d 处' % (files, sites))
    return sites


WRITE_PUTS = re.compile(
    r'(?m)^    invoke-interface \{v\d+, v\d+, [vp]\d+\}, '
    r'Landroid/content/SharedPreferences\$Editor;->put(?:String|Boolean)\([^\n]*\n'
)


def silence_migration():
    p = os.path.join(HW, 'HelloWorldActivity.smali')
    s = read(p)
    m = re.search(r'(?m)^\.method private C\(\)V\n(.*?)^\.end method', s, re.S)
    if not m:
        print('[C] ANCHOR MISS: C()')
        return 0
    body = m.group(1)
    lines = body.split('\n')
    keys = ('font_size', 'screen_mode', 'isDefaultTheme')
    n = 0
    for i, l in enumerate(lines):
        mp = re.match(r'    invoke-interface \{([vp]\d+), ([vp]\d+), ([vp]\d+)\}, '
                      r'Landroid/content/SharedPreferences\$Editor;->put', l)
        if not mp:
            continue
        kreg = mp.group(2)
        key = None
        for k in range(i - 1, max(-1, i - 9), -1):
            mk = re.match(r'    const-string ' + re.escape(kreg) + r', "(\w+)"', lines[k])
            if mk:
                key = mk.group(1)
                break
        if key in keys:
            lines[i] = '    nop'
            n += 1
    s = s[:m.start(1)] + '\n'.join(lines) + s[m.end(1):]
    write(p, s)
    print('[C] C() 版本迁移写盘静默化: %d 处' % n)
    return n


CALL = ('    invoke-static/range {p0 .. p0}, '
        'Llongbin/helloworld/PrefBootstrap;->a(Landroid/content/Context;)V\n')


def inject_onresume(name, sig):
    p = os.path.join(HW, name)
    s = read(p)
    m = re.search(r'(?m)^' + re.escape(sig) + r'\n    \.locals \d+\n', s)
    if not m:
        print('[D] ANCHOR MISS:', name)
        return
    end = m.end()
    if 'PrefBootstrap' in s[end:end + 200]:
        print('[D] skip (already injected):', name)
        return
    s = s[:end] + '\n' + CALL + s[end:]
    write(p, s)
    print('[D] 注入 onResume:', name)


def verify():
    fb = read(os.path.join(HW, 'PrefBootstrap.smali'))
    print('[verify] PrefBootstrap 只写 isDefaultTheme: %s' % (
        'font_size' not in fb and 'screen_mode' not in fb and 'apply()V' in fb))
    left = 0
    for dp, _, ns in os.walk(SMALI):
        for fn in ns:
            if fn.endswith('.smali'):
                left += len(EQ.findall(read(os.path.join(dp, fn))))
    print('[verify] 残留 equals 付费判定: %d' % left)
    for name, sig in [('SplashActivity.smali', '.method protected onResume()V'),
                      ('HelloWorldActivity.smali', '.method public onResume()V')]:
        s = read(os.path.join(HW, name))
        print('[verify] %s PrefBootstrap 调用数: %d' % (name, s.count('PrefBootstrap')))


def main():
    write(os.path.join(HW, 'PrefBootstrap.smali'), PREF_BOOTSTRAP)
    print('[0] PrefBootstrap 改为只维护 isDefaultTheme')
    a = force_equals_true()
    b = force_bool_gates()
    c = silence_migration()
    inject_onresume('SplashActivity.smali', '.method protected onResume()V')
    inject_onresume('HelloWorldActivity.smali', '.method public onResume()V')
    verify()
    if a == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
