#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成品 APK 自动验收：静态复核 + 对照表 + 可选严格断言。

用法:
  python work/verify_build.py <apk> [--baseline APK] [--profile v5|v6|none]
                              [--decompiled DIR] [--strict] [--json OUT.json]

说明:
  - 未给 --decompiled 时自动调用 apktool 反编译到 work/verify_auto/<apk名>/
  - 已反编译过的目录（如 work/verify_v5、work/verify_v6）可直接传入，省去反编译耗时
  - --strict 时任一 FAIL 项会导致退出码 1；默认只输出表格，退出码 0
  - profile 中的期望值来自本项目实测（v5 成品反编译复核，2026-11-07）
"""
import argparse
import base64
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APKTOOL = os.path.join(ROOT, 'apktool.jar')
APKSIGNER = os.path.join(ROOT, 'build-tools', 'android-14', 'lib', 'apksigner.jar')

# 期望值：键 -> (说明, 期望值, 是否严格断言)
# 数值口径见 报告_付费闸门闭合修复_v3.md / 报告_v4版本独立复核与评价.md
PROFILES = {
    'v5': {'forced_true': 44, 'gate_if_eqz': 0, 'azb_display_puts': 6},
    'v6': {'forced_true': 44, 'gate_if_eqz': 0, 'azb_display_puts': 0},
    'none': {},
}

EQ = re.compile(
    r'const-string [vp]\d+, "(landscape|24)"\s*\n\s*'
    r'invoke-virtual \{[^}]*\}, Ljava/lang/String;->equals\(Ljava/lang/Object;\)Z')
BLK = re.compile(
    r'const-string [vp]\d+, "(landscape|24)"\s*\n\s*'
    r'invoke-virtual \{[^}]*\}, Ljava/lang/String;->equals\(Ljava/lang/Object;\)Z\s*\n\s*'
    r'move-result ([vp]\d+)')
FORCED = re.compile(r'(?m)^    const/(4|16) ([vp]\d+), 0x1\n\n?    nop\n')
BOOL_GATE = re.compile(
    r'\bnop\s*\n\s*iget-boolean ([vp]\d+), [^\n]+:Z\s*\n\s*if-eqz \1, :\S+')


def run(cmd):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=600, cwd=ROOT)
        return p.returncode, p.stdout.decode('utf-8', 'ignore')
    except Exception as e:
        return -1, str(e)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def deep3(x):
    cur = x
    for _ in range(3):
        try:
            cur = base64.b64decode(cur).decode('utf-8')
        except Exception:
            return None
    return cur if cur and all(c.isprintable() for c in cur) else None


def smali_files(smali_root):
    out = []
    for dp, _, ns in os.walk(smali_root):
        for n in ns:
            if n.endswith('.smali'):
                out.append(os.path.join(dp, n))
    return out


def read(path):
    with open(path, encoding='utf-8', errors='ignore') as f:
        return f.read()


def azb_display_puts(path):
    """数据流回溯：统计 az$b 中写 font_size / screen_mode 的 put 数。"""
    if not os.path.isfile(path):
        return -1
    cur, pending, hits = {}, {}, 0
    for line in read(path).splitlines():
        st = line.strip()
        m = re.match(r'const-string ([vp]\d+), "([A-Za-z0-9+/=]+)"', st)
        if m:
            cur[m.group(1)] = deep3(m.group(2))
            continue
        m = re.match(r'invoke-static \{([vp]\d+)\}, Lr0/f;->b\(', st)
        if m:
            pending[m.group(1)] = cur.get(m.group(1))
            continue
        m = re.match(r'move-result-object ([vp]\d+)$', st)
        if m and m.group(1) in pending:
            cur[m.group(1)] = pending.pop(m.group(1))
            continue
        m = re.match(r'invoke-interface \{([^}]*)\}, '
                     r'Landroid/content/SharedPreferences\$Editor;->put\w+\(', st)
        if m:
            a = [x.strip() for x in m.group(1).split(',')]
            if len(a) > 1 and cur.get(a[1]) in ('font_size', 'screen_mode'):
                hits += 1
    return hits


def collect(apk, baseline, decompiled):
    r = {'apk': os.path.basename(apk)}
    r['size'] = os.path.getsize(apk)
    r['sha256'] = sha256_file(apk)
    r['md5'] = hashlib.md5(open(apk, 'rb').read()).hexdigest()

    # 签名
    rc, out = run(['java', '-jar', APKSIGNER, 'verify', '--verbose', '--print-certs', apk])
    r['signature'] = {v: ('Verified using v%s scheme' % v in out and 'true' in
                          out.split('Verified using v%s scheme' % v, 1)[1].split('\n', 1)[0])
                       for v in (1, 2, 3)}
    r['signature']['verifies'] = 'Verifies' in out
    dn = re.search(r'certificate DN:\s*(.+)', out)
    dg = re.search(r'certificate SHA-256 digest:\s*([0-9a-f]+)', out)
    r['cert_dn'] = dn.group(1).strip() if dn else '?'
    r['cert_sha256'] = dg.group(1)[:16] if dg else '?'

    # ZIP / DEX
    with zipfile.ZipFile(apk) as z:
        entries = {i.filename: (i.CRC, i.file_size) for i in z.infolist()}
        dex = z.read('classes.dex')
    r['entries'] = len(entries)
    r['dex_size'] = len(dex)
    r['dex_sha256'] = hashlib.sha256(dex).hexdigest()[:16]
    r['dex_strings'] = struct.unpack_from('<I', dex, 56)[0]
    r['dex_methods'] = struct.unpack_from('<I', dex, 88)[0]
    r['dex_classes'] = struct.unpack_from('<I', dex, 96)[0]
    if baseline and os.path.isfile(baseline):
        with zipfile.ZipFile(baseline) as z:
            base = {i.filename: (i.CRC, i.file_size) for i in z.infolist()}
        r['changed_vs_baseline'] = sorted(
            n for n in set(entries) & set(base) if entries[n] != base[n])
        r['added'] = sorted(set(entries) - set(base))
        r['removed'] = sorted(set(base) - set(entries))
    else:
        r['changed_vs_baseline'] = []

    # 反编译
    if not decompiled:
        decompiled = os.path.join(HERE, 'verify_auto',
                                  os.path.splitext(os.path.basename(apk))[0])
        if not os.path.isdir(os.path.join(decompiled, 'smali')):
            os.makedirs(decompiled, exist_ok=True)
            rc, out = run(['java', '-jar', APKTOOL, 'd', '-f', '-o', decompiled, apk])
            if rc != 0:
                print('[ERROR] apktool 反编译失败:\n' + out[-2000:], file=sys.stderr)
                sys.exit(2)
    r['decompiled'] = decompiled
    smali = os.path.join(decompiled, 'smali')
    files = smali_files(smali)
    r['smali_files'] = len(files)

    forced = eq_left = eq_nonbranch = gate_left = bool_left = 0
    urls = set()
    loadlib = 0
    for p in files:
        s = read(p)
        forced += len(FORCED.findall(s))
        bool_left += len(BOOL_GATE.findall(s))
        loadlib += len(re.findall(r'Ljava/lang/System;->loadLibrary\(', s))
        for m in re.finditer(r'const-string [vp]\d+, "(https?://[^\" ]+)"', s):
            urls.add(m.group(1))
        for m in EQ.finditer(s):
            eq_left += 1
            if re.search(r'\bif-nez\b', s[m.end():m.end() + 320]):
                eq_nonbranch += 1
        for m in BLK.finditer(s):
            tail = s[m.end():m.end() + 320]
            if re.search(r'\bif-eqz ' + re.escape(m.group(1)) + r', :\S+', tail):
                gate_left += 1
    r['forced_true'] = forced
    r['eq_literals_left'] = eq_left
    r['eq_if_nez_layout'] = eq_nonbranch
    r['gate_if_eqz_left'] = gate_left
    r['bool_gate_left'] = bool_left
    r['load_library'] = loadlib
    r['ideacalc_plain_urls'] = sorted(u for u in urls if 'ideacalc.cn' in u)

    hw = os.path.join(smali, 'longbin', 'helloworld')
    pb = os.path.join(hw, 'PrefBootstrap.smali')
    r['prefbootstrap'] = ('font_size' not in read(pb) and 'screen_mode' not in read(pb)
                          and 'apply()V' in read(pb)) if os.path.isfile(pb) else None
    act = os.path.join(hw, 'HelloWorldActivity.smali')
    if os.path.isfile(act):
        s = read(act)
        mr = re.search(r'\.method public onResume\(\)V(.*?)\.end method', s, re.S)
        r['main_onresume_bootstrap'] = bool(mr and 'PrefBootstrap' in mr.group(1))
        mc = re.search(r'\.method private C\(\)V(.*?)\.end method', s, re.S)
        r['migration_puts'] = len(re.findall(r'->put(?:String|Boolean)\(', mc.group(1))) if mc else -1
        r['D_return_void'] = bool(re.search(
            r'\.method private D\(\)V\s*\n\s*\.locals \d+\s*\n\s*return-void', s))
    spl = os.path.join(hw, 'SplashActivity.smali')
    if os.path.isfile(spl):
        s = read(spl)
        ms = re.search(r'\.method protected onResume\(\)V(.*?)\.end method', s, re.S)
        r['splash_onresume_bootstrap'] = bool(ms and 'PrefBootstrap' in ms.group(1))
    po = os.path.join(smali, 'r0', 'p.smali')
    if os.path.isfile(po):
        s = read(po)
        r['update_null'] = bool(re.search(
            r'\.method public static o\(\)Lr0/k;.*?const/4 v0, 0x0.*?return-object v0.*?\.end method',
            s, re.S))
    r['azb_display_puts'] = azb_display_puts(os.path.join(hw, 'az$b.smali'))
    man = os.path.join(decompiled, 'AndroidManifest.xml')
    if os.path.isfile(man):
        s = read(man)
        r['exported_components'] = [
            (re.search(r'android:name="([^"]+)"', x.group(0)).group(1)
             if re.search(r'android:name="([^"]+)"', x.group(0)) else '?')
            for x in re.finditer(r'<(?:activity|service|receiver|provider)[^>]*android:exported="true"[^>]*>', s)]
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('apk')
    ap.add_argument('--baseline')
    ap.add_argument('--profile', default='none', choices=sorted(PROFILES))
    ap.add_argument('--decompiled')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--json')
    a = ap.parse_args()
    apk = a.apk if os.path.isabs(a.apk) else os.path.join(ROOT, a.apk)
    r = collect(apk, a.baseline, a.decompiled)
    exp = PROFILES[a.profile]

    rows = [
        ('文件', '大小', r['size'], None),
        ('文件', 'SHA-256', r['sha256'], None),
        ('文件', 'MD5', r['md5'], None),
        ('签名', 'v1/v2/v3', '/'.join(str(r['signature'][v]) for v in (1, 2, 3)), 'True/True/True'),
        ('签名', 'Verifies', r['signature']['verifies'], True),
        ('签名', '证书', '%s / %s…' % (r['cert_dn'], r['cert_sha256']), None),
        ('ZIP', '条目数', r['entries'], None),
        ('ZIP', '相对基线改动', ', '.join(r['changed_vs_baseline']) or '(无基线)', None),
        ('DEX', 'size / sha256', '%d / %s…' % (r['dex_size'], r['dex_sha256']), None),
        ('DEX', 'strings/methods/classes', '%d/%d/%d' % (
            r['dex_strings'], r['dex_methods'], r['dex_classes']), None),
        ('DEX', 'smali 文件数', r['smali_files'], None),
        ('闸门', '强制为真痕迹', r['forced_true'], exp.get('forced_true')),
        ('闸门', '残留 equals 字面量', r['eq_literals_left'], None),
        ('闸门', '  └ if-nez 布局选择(豁免)', r['eq_if_nez_layout'], None),
        ('闸门', '残留付费 if-eqz', r['gate_if_eqz_left'], exp.get('gate_if_eqz', 0)),
        ('闸门', '残留布尔闸门', r['bool_gate_left'], None),
        ('闸门', 'az$b 写显示设置 put', r['azb_display_puts'], exp.get('azb_display_puts')),
        ('自举', 'PrefBootstrap 只写无关键', r['prefbootstrap'], True),
        ('自举', 'Main.onResume', r.get('main_onresume_bootstrap'), True),
        ('自举', 'Splash.onResume', r.get('splash_onresume_bootstrap'), True),
        ('更新', 'r0/p.o() 返回 null', r.get('update_null'), True),
        ('更新', 'D() return-void', r.get('D_return_void'), True),
        ('其它', 'System.loadLibrary 调用', r['load_library'], None),
        ('其它', 'ideacalc 明文 URL', len(r['ideacalc_plain_urls']), None),
        ('其它', 'exported=true 组件', len(r['exported_components']), None),
    ]

    fails = []
    print('=' * 78)
    print('APK 自动验收: %s   (profile=%s)' % (r['apk'], a.profile))
    print('=' * 78)
    print('%-6s %-28s %-30s %s' % ('类别', '指标', '实测', '状态'))
    print('-' * 78)
    for cat, name, got, want in rows:
        if want is None:
            st = 'INFO'
        elif got == want:
            st = 'PASS'
        else:
            st = 'FAIL (期望 %s)' % (want,)
            fails.append('%s: 实测 %s / 期望 %s' % (name, got, want))
        print('%-6s %-28s %-30s %s' % (cat, name, str(got)[:30], st))
    print('-' * 78)
    print('反编译目录: %s' % r['decompiled'])
    if r['ideacalc_plain_urls']:
        print('ideacalc 明文端点: %s' % ', '.join(r['ideacalc_plain_urls']))
    if r['exported_components']:
        print('exported 组件: %s' % ', '.join(r['exported_components']))
    if fails:
        print('\n%d 项未达标:' % len(fails))
        for x in fails:
            print('  - ' + x)
    else:
        print('\n所有断言通过。')
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'metrics': r, 'fails': fails}, f, ensure_ascii=False, indent=2)
        print('JSON 已写入: %s' % a.json)
    if a.strict and fails:
        sys.exit(1)


if __name__ == '__main__':
    main()
