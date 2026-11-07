#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v6 补丁：屏蔽 az$b（手动授权回调）对 font_size / screen_mode 的写盘。

背景：
  v5 已把付费判定结果强制为真，SharedPreferences 的三值不再影响付费态；
  但 az$b.handleMessage() 的三个授权分支仍会 putString 写 font_size="24" /
  screen_mode="landscape"，会把用户自己设置的字号与显示模式改掉（报告 12.8）。

做法：
  1) 用数据流回溯定位键解码结果为 font_size / screen_mode 的 put 调用（实测 6 处）；
  2) 把这些 invoke-interface 替换为 3 条 nop（invoke-interface 占 3 个 code unit，
     nop 每条 1 个，等长；返回值原本就被忽略，故不动任何寄存器定义与类型流）；
  3) 其余 12 处 put（isDefaultTheme / expired_time / buyer_account 等）与 commit() 原样保留。

幂等：已打补丁时数据流回溯返回 0 处，脚本打印 skip 并不改写文件。
"""
import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, 'v6')
TARGET = os.path.join(BASE, 'smali', 'longbin', 'helloworld', 'az$b.smali')
EXPECT = 6

DISPLAY_KEYS = ('font_size', 'screen_mode')


def deep3(x):
    cur = x
    for _ in range(3):
        try:
            cur = base64.b64decode(cur).decode('utf-8')
        except Exception:
            return None
    return cur if cur and all(c.isprintable() for c in cur) else None


def locate(lines):
    """返回写显示设置的 put 调用所在行索引（0-based）。"""
    cur, pending, hits = {}, {}, []
    for i, line in enumerate(lines):
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
            if len(a) > 1 and cur.get(a[1]) in DISPLAY_KEYS:
                hits.append((i, a[1], cur.get(a[1])))
    return hits


def main():
    if not os.path.isfile(TARGET):
        print('[ERROR] 基线不存在: %s' % TARGET, file=sys.stderr)
        print('先执行: cp -r work/verify_v5 work/v6', file=sys.stderr)
        sys.exit(2)

    with open(TARGET, encoding='utf-8', newline='') as f:
        src = f.read()
    lines = src.splitlines(True)
    eol = '\r\n' if lines and lines[0].endswith('\r\n') else '\n'

    hits = locate(lines)
    if not hits:
        print('[skip] 未发现写 font_size / screen_mode 的 put —— 可能已打过补丁，未改动文件。')
        print('       当前 nop 行数:', sum(1 for l in lines if l.strip() == 'nop'))
        return
    if len(hits) != EXPECT:
        print('[ERROR] 目标 put 数 %d != 期望 %d，拒绝改动。命中: %s'
              % (len(hits), EXPECT, hits), file=sys.stderr)
        sys.exit(3)

    print('[v6] 定位到 %d 处写显示设置的 put:' % len(hits))
    for i, reg, key in hits:
        print('   行%-5d 键寄存器 %-4s -> %s | %s' % (i + 1, reg, key, lines[i].strip()[:96]))

    for i, _, _ in hits:
        indent = re.match(r'[ \t]*', lines[i]).group(0)
        lines[i] = (indent + 'nop' + eol) * 3

    with open(TARGET, 'w', encoding='utf-8', newline='') as f:
        f.writelines(lines)

    # 复验：重新读取落盘文件，按真实行统计
    with open(TARGET, encoding='utf-8') as f:
        after_lines = f.read().splitlines()
    after = locate(after_lines)
    nops = sum(1 for l in after_lines if l.strip() == 'nop')
    print('[v6] 改写完成。复验残留目标 put =', len(after))
    print('[v6] 文件 nop 行数 = %d (= %d 处 × 3 条等长 nop)' % (nops, len(hits)))
    if after:
        print('[ERROR] 仍有残留，补丁不完整', file=sys.stderr)
        sys.exit(4)


if __name__ == '__main__':
    main()
