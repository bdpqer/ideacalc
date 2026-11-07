# -*- coding: utf-8 -*-
"""计算管家 4.4.3：去除授权/付费判定（修正版）。

修正点：第一版把 const-string/const 默认值指令一起删掉，导致这些寄存器在后续
代码里被当作整数/布尔复用时变成 Undefined，触发 VerifyError。
本版只替换 invoke-interface getBoolean 与紧随的 move-result 两条，
保留 key 常量与默认值常量的寄存器定义，最小改动。
"""
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth_base')
SMALI = os.path.join(ROOT, 'smali')

RE_INV = re.compile(
    r'    invoke-interface \{(?P<obj>[vp][0-9]+), (?P<key>[vp][0-9]+), (?P<def>[vp][0-9]+)\}, '
    r'Landroid/content/SharedPreferences;->getBoolean\(Ljava/lang/String;Z\)Z\s*'
    r'    move-result (?P<dst>[vp][0-9]+)'
)

RE_KEY = re.compile(r'const-string (?P<reg>[vp][0-9]+), "isDefaultTheme"')

RE_PUT = re.compile(
    r'    const-string (?P<key>[vp][0-9]+), "isDefaultTheme"\s*'
    r'    invoke-interface \{(?P<obj>[vp][0-9]+), (?P=key), (?P<val>[vp][0-9]+)\}, '
    r'Landroid/content/SharedPreferences\$Editor;->putBoolean\(Ljava/lang/String;Z\)'
    r'Landroid/content/SharedPreferences\$Editor;'
)


def const_true(dst):
    n = int(dst[1:])
    return ('    const/4 %s, 0x1' if n <= 15 else '    const/16 %s, 0x1') % dst


def patch_text(text):
    stats = {'get': 0, 'put': 0}

    def sub_get(m):
        # 向前回溯 500 字符，确认 key 寄存器来自 "isDefaultTheme" 常量
        head = text[max(0, m.start() - 500):m.start()]
        keys = RE_KEY.findall(head)
        if not keys or keys[-1] != m.group('key'):
            return m.group(0)
        stats['get'] += 1
        return const_true(m.group('dst'))

    def sub_put(m):
        stats['put'] += 1
        return const_true(m.group('val')) + '\n\n' + m.group(0)

    text = RE_INV.sub(sub_get, text)
    text = RE_PUT.sub(sub_put, text)
    return text, stats


def main():
    total = {'get': 0, 'put': 0, 'files': 0}
    for dirpath, _, names in os.walk(SMALI):
        for name in names:
            if not name.endswith('.smali'):
                continue
            p = os.path.join(dirpath, name)
            with open(p, encoding='utf-8', errors='ignore') as f:
                src = f.read()
            if 'isDefaultTheme' not in src:
                continue
            dst, st = patch_text(src)
            if st['get'] or st['put']:
                with open(p, 'w', encoding='utf-8', newline='') as f:
                    f.write(dst)
                total['files'] += 1
                total['get'] += st['get']
                total['put'] += st['put']
                print('  %-58s GET=%d PUT=%d' % (os.path.relpath(p, SMALI), st['get'], st['put']))
    print('=== 合计：%d 文件 / 读取点 %d / 写入点 %d ===' % (
        total['files'], total['get'], total['put']))

    # 复查：仍能读到 isDefaultTheme 的 getBoolean 是否清零（排除结果被丢弃的调用）
    left = 0
    for dirpath, _, names in os.walk(SMALI):
        for name in names:
            if not name.endswith('.smali'):
                continue
            p = os.path.join(dirpath, name)
            with open(p, encoding='utf-8', errors='ignore') as f:
                s = f.read()
            for m in RE_INV.finditer(s):
                head = s[max(0, m.start() - 500):m.start()]
                keys = RE_KEY.findall(head)
                if keys and keys[-1] == m.group('key'):
                    left += 1
            # 丢弃返回值的调用（invoke 后直接跟标签/指令）
            for m in re.finditer(r'const-string ([vp][0-9]+), "isDefaultTheme"', s):
                pass
    print('未替换的有效读取点：', left)


if __name__ == '__main__':
    main()
