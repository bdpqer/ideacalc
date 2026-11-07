# -*- coding: utf-8 -*-
"""计算管家 4.4.3：去除授权/付费判定。

原理：付费开关是 SharedPreferences 布尔键 isDefaultTheme，全应用 26 处
getBoolean("isDefaultTheme", ...) 读取决定功能是否解锁。本脚本把这些读取
调用整段替换为常量 true，使所有付费闸门无条件通过；同时把升级路径里唯一
一处 putBoolean("isDefaultTheme", false) 改为 true，避免版本升级重置。
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth_base')
SMALI = os.path.join(ROOT, 'smali')

RE_GET_WITH_CONST = re.compile(
    r'    const-string (?P<key>[vp][0-9]+), "isDefaultTheme"\s*'
    r'    const(?:/4|/16|/high16) (?P<def>[vp][0-9]+), 0x0{1,8}\s*'
    r'    invoke-interface \{(?P<obj>[vp][0-9]+), (?P=key), (?P=def)\}, '
    r'Landroid/content/SharedPreferences;->getBoolean\(Ljava/lang/String;Z\)Z\s*'
    r'    move-result (?P<dst>[vp][0-9]+)'
)

RE_GET_PLAIN = re.compile(
    r'    const-string (?P<key>[vp][0-9]+), "isDefaultTheme"\s*'
    r'    invoke-interface \{(?P<obj>[vp][0-9]+), (?P=key), (?P<def>[vp][0-9]+)\}, '
    r'Landroid/content/SharedPreferences;->getBoolean\(Ljava/lang/String;Z\)Z\s*'
    r'    move-result (?P<dst>[vp][0-9]+)'
)

RE_PUT = re.compile(
    r'    const-string (?P<key>[vp][0-9]+), "isDefaultTheme"\s*'
    r'    invoke-interface \{(?P<obj>[vp][0-9]+), (?P=key), (?P<val>[vp][0-9]+)\}, '
    r'Landroid/content/SharedPreferences\$Editor;->putBoolean\(Ljava/lang/String;Z\)'
    r'Landroid/content/SharedPreferences\$Editor;'
)


def reg_num(reg):
    return int(reg[1:])


def const_true(dst):
    n = reg_num(dst)
    if n <= 15:
        return '    const/4 %s, 0x1' % dst
    return '    const/16 %s, 0x1' % dst


def patch_text(text):
    stats = {'get': 0, 'put': 0}

    def sub_get(m):
        stats['get'] += 1
        return const_true(m.group('dst'))

    def sub_get_plain(m):
        stats['get'] += 1
        return const_true(m.group('dst'))

    def sub_put(m):
        stats['put'] += 1
        return const_true(m.group('val')) + '\n\n' + m.group(0)

    text = RE_GET_WITH_CONST.sub(sub_get, text)
    text = RE_GET_PLAIN.sub(sub_get_plain, text)
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
    print('=== 合计：%d 个文件，读取点改写 %d 处，写入点改写 %d 处 ===' % (
        total['files'], total['get'], total['put']))
    # 复查：是否还有残留 getBoolean("isDefaultTheme")
    left = 0
    for dirpath, _, names in os.walk(SMALI):
        for name in names:
            if not name.endswith('.smali'):
                continue
            p = os.path.join(dirpath, name)
            with open(p, encoding='utf-8', errors='ignore') as f:
                s = f.read()
            if '"isDefaultTheme"' in s:
                for m in re.finditer(r'"isDefaultTheme"', s):
                    tail = s[m.start():m.start() + 400]
                    if 'getBoolean' in tail.split('move-result')[0] or 'putBoolean' in tail.split('return')[0]:
                        pass
                # 精确复查：统计仍带 getBoolean 的段
                if re.search(r'"isDefaultTheme"\s*[^\n]*\n\s*\n\s*const[^\n]*\n\s*\n\s*invoke-interface[^\n]*getBoolean', s):
                    left += 1
                    print('  残留疑似读取点：', os.path.relpath(p, SMALI))
    print('残留读取点文件数：', left)


if __name__ == '__main__':
    main()
