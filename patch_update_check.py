# -*- coding: utf-8 -*-
"""去除计算管家 4.4.3 的联网更新检查（整体替换方法体版）。

链路：
  HelloWorldActivity.Y() -> D() -> HelloWorldActivity$b3(AsyncTask)
    -> Lr0/p;->o()Lr0/k;   // GET http://www.ideacalc.cn/update/updateInfo.xml
    -> HelloWorldActivity$a3.handleMessage：服务端 version 高于本地则弹更新框，
       点"下载"由 HelloWorldActivity$r 用 ACTION_VIEW 打开 downloadUrl（浏览器下载，非静默安装）

做法：把 r0/p.o() 与 HelloWorldActivity.D() 的方法体整体替换为"直接返回"：
  - o() 返回 null -> 不再发 HTTP 请求；$b3 把 null 放进 Message.obj，
    handler 的 if-eqz 分支走"无结果"路径，不会弹更新框。
  - D() 直接 return-void -> 连"是否到时间"的判断与时间戳写入都不再执行。
不用"插入 return 保留原代码"的写法，避免 return 之后的死代码被校验器判为 Undefined 寄存器。

用法：先把成品 APK 反编译到 work/auth_upd，再运行本脚本，然后 apktool b / zipalign / apksigner。
"""
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth_upd')
SMALI = os.path.join(ROOT, 'smali')

NEW_O = ('    .locals 4\n'
         '\n'
         '    const/4 v0, 0x0\n'
         '\n'
         '    return-object v0\n'
         '\n')

NEW_D = ('    .locals 10\n'
         '\n'
         '    return-void\n'
         '\n')


def replace_body(path, signature, new_body):
    with open(path, encoding='utf-8', errors='ignore') as f:
        s = f.read()
    pat = re.compile(r'(' + re.escape(signature) + r'\n)(.*?)(\.end method)', re.S)
    m = pat.search(s)
    if not m:
        print('ANCHOR MISS:', signature)
        return False
    if m.group(2) == new_body:
        print('skip (already clean):', signature)
        return True
    s = s[:m.start(2)] + new_body + s[m.start(3):]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(s)
    print('body replaced:', signature)
    return True


def main():
    ok1 = replace_body(os.path.join(SMALI, 'r0', 'p.smali'), '.method public static o()Lr0/k;', NEW_O)
    ok2 = replace_body(os.path.join(SMALI, 'longbin', 'helloworld', 'HelloWorldActivity.smali'),
                       '.method private D()V', NEW_D)
    print('OK' if ok1 and ok2 else 'FAILED')


if __name__ == '__main__':
    main()
