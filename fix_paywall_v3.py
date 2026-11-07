# -*- coding: utf-8 -*-
"""计算管家 4.4.3：闭合付费闸门（v3 修复）。

针对 v2 的结构性缺陷：只把 isDefaultTheme 的 getBoolean 常量化，
font_size="24" / screen_mode="landscape" 的字符串比较仍然活着，
付费态完全依赖 PrefBootstrap 启动时写 SharedPreferences 维持。

本补丁做三件事（均为最小侵入，不删任何指令定义）：

1) 闸门分支 nop 化：把付费判定块里 equals("landscape"/"24") 结果后的
   `if-eqz vN, :cond` 替换为等长的 `nop`。不碰 invoke-virtual / move-result，
   因此不存在寄存器 Undefined 或 p 寄存器 > 15 的 const/4 越界问题。
   仅处理「同文件内 landscape 与 "24" 成对出现」的判定块，
   排除 SplashActivity.g() 的 if-nez（真实字号显示逻辑）。

2) HelloWorldActivity.C() 版本迁移写入改为已购买态：
   font_size "26" -> "24"，screen_mode "normal" -> "landscape"。
   C() 在 onCreate 中位于 PrefBootstrap 之后，原逻辑会破坏显示值。

3) SplashActivity / HelloWorldActivity 的 onResume 注入 PrefBootstrap，
   每次回到前台重写三值，兜住 az$b 等通过多层 base64 动态解码键名的写入。

幂等：重复运行不会重复插入或重复替换。
"""
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fix_v3')
SMALI = os.path.join(ROOT, 'smali')

CALL = '    invoke-static {p0}, Llongbin/helloworld/PrefBootstrap;->a(Landroid/content/Context;)V\n'
# HelloWorldActivity.onResume 是 .locals 25，p0 实际为 v25（> 15），
# 普通 invoke-static 只接受 v0-v15，必须用 range 格式。
CALL_RANGE = ('    invoke-static/range {p0 .. p0}, '
              'Llongbin/helloworld/PrefBootstrap;->a(Landroid/content/Context;)V\n')

# const-string "landscape"/"24" -> String.equals -> move-result
BLOCK = re.compile(
    r'const-string ([vp]\d+), "(landscape|24)"\s*\n\s*\n?\s*'
    r'invoke-virtual \{[vp]\d+, [vp]\d+\}, Ljava/lang/String;->equals\(Ljava/lang/Object;\)Z\s*\n\s*\n?\s*'
    r'move-result ([vp]\d+)'
)


def patch_gates():
    total_files = total_branches = 0
    skipped = []
    for dp, _, ns in os.walk(SMALI):
        for fn in ns:
            if not fn.endswith('.smali'):
                continue
            p = os.path.join(dp, fn)
            s = open(p, encoding='utf-8', errors='ignore').read()
            cands = list(BLOCK.finditer(s))
            if not cands:
                continue
            lits = {m.group(2) for m in cands}
            # 付费判定块特征：同一文件内 landscape 与 "24" 成对
            if not {'landscape', '24'} <= lits:
                skipped.append((os.path.relpath(p, SMALI), len(cands)))
                continue
            edits = []
            for m in cands:
                dst = m.group(3)
                tail = s[m.end():m.end() + 320]
                br = re.search(r'\bif-eqz ' + re.escape(dst) + r', (:\S+)', tail)
                if not br:
                    continue
                # 分支之前不得有对该结果寄存器的重新赋值
                prefix = tail[:br.start()]
                if re.search(r'\b(?:const|move|iget|aget|move-result)[^\n]*\b' + re.escape(dst) + r'\b', prefix):
                    continue
                abs_start = m.end() + br.start()
                abs_end = m.end() + br.end()
                edits.append((abs_start, abs_end, s[abs_start:abs_end]))
            if not edits:
                continue
            # 从后往前替换，保持偏移有效
            for start, end, old in sorted(edits, reverse=True):
                # 等长替换：if-eqz vN, :label -> nop（保留原有 4 空格缩进）
                s = s[:start] + 'nop' + s[end:]
            open(p, 'w', encoding='utf-8', newline='').write(s)
            total_files += 1
            total_branches += len(edits)
    print('[1] 闸门分支 nop 化: %d 文件 / %d 处' % (total_files, total_branches))
    print('    排除的非闸门文件: %s' % skipped)
    return total_branches


def patch_bool_gates():
    """闭合经字段传递的第三值 isDefaultTheme 判定。

    少数判定块把布尔值先存进内部类字段，再 `iget-boolean` + `if-eqz` 比较。
    v2 只常量化了 getBoolean 读取点，这里把该分支也 nop 化，
    使三个条件全部不依赖任何数据源。
    """
    pat = re.compile(
        r'\bnop\s*\n\s*\n?\s*iget-boolean ([vp]\d+), [^\n]+:Z\s*\n\s*\n?\s*'
        r'if-eqz \1, :\S+'
    )
    n = files = 0
    for dp, _, ns in os.walk(SMALI):
        for fn in ns:
            if not fn.endswith('.smali'):
                continue
            p = os.path.join(dp, fn)
            s = open(p, encoding='utf-8', errors='ignore').read()
            cands = list(BLOCK.finditer(s))
            if not ({'landscape', '24'} <= {m.group(2) for m in cands}):
                continue
            hits = []
            for m in pat.finditer(s):
                seg = s[m.start():m.end()]
                br = re.search(r'if-eqz [vp]\d+, :\S+', seg)
                hits.append((m.start() + br.start(), m.start() + br.end()))
            if not hits:
                continue
            for start, end in sorted(hits, reverse=True):
                s = s[:start] + 'nop' + s[end:]
            open(p, 'w', encoding='utf-8', newline='').write(s)
            files += 1
            n += len(hits)
    print('[1b] 布尔闸门 nop 化: %d 文件 / %d 处' % (files, n))
    return n


def patch_version_migration():
    p = os.path.join(SMALI, 'longbin', 'helloworld', 'HelloWorldActivity.smali')
    s = open(p, encoding='utf-8', errors='ignore').read()
    m = re.search(r'\.method private C\(\)V(.*?)\.end method', s, re.S)
    if not m:
        print('[2] ANCHOR MISS: C()')
        return 0
    body = m.group(1)
    n = 0
    for old, new in [('const-string v7, "26"', 'const-string v7, "24"'),
                     ('const-string v7, "normal"', 'const-string v7, "landscape"')]:
        if old in body:
            body = body.replace(old, new, 1)
            n += 1
    if n:
        s = s[:m.start(1)] + body + s[m.end(1):]
        open(p, 'w', encoding='utf-8', newline='').write(s)
    print('[2] C() 版本迁移常量改为已购买态: %d 处' % n)
    return n


ONRESUME_TARGETS = [
    ('SplashActivity.smali',
     '    invoke-super {p0}, Landroid/app/Activity;->onResume()V\n', CALL),
    ('HelloWorldActivity.smali',
     '.method public onResume()V\n    .locals 25\n', CALL_RANGE),
]


def patch_onresume():
    n = 0
    for name, anchor, call in ONRESUME_TARGETS:
        p = os.path.join(SMALI, 'longbin', 'helloworld', name)
        s = open(p, encoding='utf-8', errors='ignore').read()
        if anchor not in s:
            print('[3] ANCHOR MISS:', name)
            continue
        # 只检查 onResume 方法体内是否已有调用
        pos = s.index(anchor)
        body = s[pos:pos + 400]
        if 'PrefBootstrap' in body:
            print('[3] skip (already injected):', name)
            continue
        s = s[:pos + len(anchor)] + '\n' + call + s[pos + len(anchor):]
        open(p, 'w', encoding='utf-8', newline='').write(s)
        print('[3] injected onResume:', name)
        n += 1
    return n


def verify():
    # 复核：成对文件中不应再有 equals 结果后的 if-eqz
    left = []
    for dp, _, ns in os.walk(SMALI):
        for fn in ns:
            if not fn.endswith('.smali'):
                continue
            p = os.path.join(dp, fn)
            s = open(p, encoding='utf-8', errors='ignore').read()
            cands = list(BLOCK.finditer(s))
            if not ({'landscape', '24'} <= {m.group(2) for m in cands}):
                continue
            for m in cands:
                dst = m.group(3)
                tail = s[m.end():m.end() + 320]
                if re.search(r'\bif-eqz ' + re.escape(dst) + r', :\S+', tail):
                    left.append(os.path.relpath(p, SMALI))
    print('[verify] 残留付费闸门 if-eqz: %d %s' % (len(left), sorted(set(left))[:6]))
    for name, _, _ in ONRESUME_TARGETS:
        p = os.path.join(SMALI, 'longbin', 'helloworld', name)
        s = open(p, encoding='utf-8', errors='ignore').read()
        print('[verify] %s onResume PrefBootstrap 调用数: %d' % (
            name, s.count('PrefBootstrap')))


def main():
    patch_gates()
    patch_bool_gates()
    patch_version_migration()
    patch_onresume()
    verify()


if __name__ == '__main__':
    main()
