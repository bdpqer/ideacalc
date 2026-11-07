# -*- coding: utf-8 -*-
"""计算管家 4.4.3 精简去广告：修改 apktool 反编译目录。

策略：保留类名/方法签名/字段（所有引用仍然有效），只把广告、统计、
一键登录 SDK 的方法体替换为空实现；再短路少数会拿到 null 返回值的
初始化入口，删除清单组件、隐私相关权限和大块广告资源。
"""
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'smali_src')
SMALI = os.path.join(ROOT, 'smali')

SDK_DIRS = [
    'com/qq/e',       # 广点通 + HX 聚合广告
    'com/umeng',      # 友盟统计 / 友盟一键登录封装
    'com/mobile/auth',  # 运营商一键登录
    'com/nirvana',    # 号码认证内核
    'com/cmic',       # 移动认证
    'com/alicom',     # 阿里通信认证
    'com/bun',        # MSA OAID
]

# 这些自有方法会接收 SDK 返回的对象，短路以免空指针
SHORT_METHODS = {
    'longbin/helloworld/HelloWorldActivity.smali': ['b0'],
    'longbin/helloworld/SplashActivity.smali': ['d', 'h', 'l'],
}

SDK_COMPONENTS = [
    'com.qq.e.o.simpl.ADActivity',
    'com.qq.e.o.ads.v2.download.HXDownloadPrivacyActivity',
    'com.qq.e.o.utils.support.PermissionActivity',
    'com.qq.e.o.simpl.VideoActivity',
    'com.qq.e.o.game.HXADActivityGameList',
    'com.qq.e.o.game.HXADActivityGame',
    'com.qq.e.o.dl.dl.MyDownloadService',
    'com.qq.e.o.dl.DownloadReceiver',
    'com.qq.e.o.h5.HXFileProvider',
    'com.qq.e.comm.DownloadService',
    'com.qq.e.ads.ADActivity',
    'com.qq.e.ads.PortraitADActivity',
    'com.qq.e.ads.LandscapeADActivity',
    'com.qq.e.ads.RewardvideoPortraitADActivity',
    'com.qq.e.ads.RewardvideoLandscapeADActivity',
    'com.qq.e.ads.DialogActivity',
    'com.qq.e.comm.GDTFileProvider',
    'com.mobile.auth.gatewayauth.LoginAuthActivity',
    'com.mobile.auth.gatewayauth.PrivacyDialogActivity',
    'com.mobile.auth.gatewayauth.activity.AuthWebVeiwActivity',
]

DROP_PERMISSIONS = [
    'android.permission.READ_PHONE_STATE',
    'android.permission.ACCESS_COARSE_LOCATION',
    'android.permission.REQUEST_INSTALL_PACKAGES',
    'android.permission.QUERY_ALL_PACKAGES',
    'android.permission.CHANGE_NETWORK_STATE',
    'android.permission.CHANGE_WIFI_STATE',
    'com.android.launcher.permission.READ_SETTINGS',
    'com.asus.msa.SupplementaryDID.ACCESS',
    'freemme.permission.msa',
    'com.google.android.gms.permission.AD_ID',
]

DROP_PATHS = [
    'assets/gdt_plugin',
    'assets/supplierconfig.json',
    'lib/arm64-v8a/libumeng-spy.so',
    'lib/armeabi-v7a/libumeng-spy.so',
    'lib/arm64-v8a/libalicomphonenumberauthsdk_core.so',
    'lib/armeabi-v7a/libalicomphonenumberauthsdk_core.so',
    'bin',
    'libs',
    'unknown/bin',
]


def ret_instructions(sig):
    """根据方法签名生成安全的返回值指令"""
    m = re.search(r'\)([^\s]+)\s*$', sig)
    t = m.group(1) if m else 'V'
    if t == 'V':
        return ['    return-void']
    if t in ('J', 'D'):
        return ['    const-wide/16 v0, 0x0', '    return-wide v0']
    if t in ('Z', 'B', 'S', 'C', 'I', 'F'):
        return ['    const/4 v0, 0x0', '    return v0']
    return ['    const/4 v0, 0x0', '    return-object v0']


def regs_for(sig, body):
    """保留寄存器声明；保证返回指令需要的寄存器可用"""
    need = 2 if re.search(r'\)([JD])\s*$', sig) else (1 if not sig.rstrip().endswith(')V') else 0)
    for ln in body:
        s = ln.strip()
        m = re.match(r'\.(locals|registers)\s+(\d+)', s)
        if m:
            kind, n = m.group(1), int(m.group(2))
            if n < need:
                n = need
            return '    .%s %d' % (kind, n)
    return '    .locals %d' % max(need, 1)


def stub_sdk(text):
    """清空 SDK 方法体；构造函数保留原样，抽象方法跳过"""
    lines = text.splitlines(True)
    out = []
    i = 0
    changed = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith('.method '):
            out.append(line)
            i += 1
            continue
        sig = line.strip()
        # 找到对应的 .end method
        j = i + 1
        while j < len(lines) and not lines[j].startswith('.end method'):
            j += 1
        body = lines[i + 1:j]
        end = lines[j] if j < len(lines) else ''
        is_ctor = 'constructor <init>' in sig
        is_abstract = re.search(r'\b(abstract|native)\b', sig) is not None
        out.append(line)
        if is_ctor or is_abstract:
            out.extend(body)
        else:
            out.append(regs_for(sig, body) + '\n')
            out.extend(x + '\n' for x in ret_instructions(sig))
            changed += 1
        if end:
            out.append(end)
        i = j + 1
    return ''.join(out), changed


def short_methods(text, names, timer=False):
    """把指定 ()V 方法整体替换为 return-void"""
    lines = text.splitlines(True)
    out = []
    i = 0
    hit = []
    while i < len(lines):
        line = lines[i]
        if not line.startswith('.method '):
            out.append(line)
            i += 1
            continue
        sig = line.strip()
        j = i + 1
        while j < len(lines) and not lines[j].startswith('.end method'):
            j += 1
        matched = None
        for n in names:
            if re.search(r'\b' + re.escape(n) + r'\(\)V\s*$', sig):
                matched = n
                break
        out.append(line)
        if matched:
            out.append('    .locals 1\n')
            out.append('    return-void\n')
            hit.append(matched)
        elif timer and matched is None and re.search(r'\bg\(\)V\s*$', sig):
            # 启动页不再等待 1.5 秒
            body = ''.join(lines[i + 1:j]).replace('0x5dc', '0x0').replace('0x5DC', '0x0')
            out.append(body)
        else:
            out.extend(lines[i + 1:j])
        if j < len(lines):
            out.append(lines[j])
        i = j + 1
    return ''.join(out), hit


def strip_manifest(text):
    lines = text.splitlines(True)
    kill = set(SDK_COMPONENTS)
    perms = set(DROP_PERMISSIONS)
    out = []
    i = 0
    removed = []
    while i < len(lines):
        line = lines[i]
        m = re.match(r'\s*<([A-Za-z][\w.\-]*)\b', line)
        if m:
            tag = m.group(1)
            nm = re.search(r'android:name="([^"]+)"', line)
            doomed = False
            if tag == 'uses-permission' and nm and nm.group(1) in perms:
                doomed = True
            elif tag in ('activity', 'service', 'receiver', 'provider', 'activity-alias') and nm and nm.group(1) in kill:
                doomed = True
            if doomed:
                removed.append(nm.group(1) if nm else tag)
                if line.rstrip().endswith('/>'):
                    i += 1
                    continue
                depth = 1
                i += 1
                while i < len(lines):
                    if re.search(r'<' + tag + r'\b', lines[i]):
                        depth += 1
                    if '</' + tag + '>' in lines[i]:
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
                continue
        out.append(line)
        i += 1
    return ''.join(out), removed


def main():
    print('=== 1) 清空 SDK 方法体 ===')
    total_files = total_methods = 0
    for d in SDK_DIRS:
        base = os.path.join(SMALI, *d.split('/'))
        if not os.path.isdir(base):
            print('  (不存在，跳过)', d)
            continue
        fc = mc = 0
        for dp, _, fs in os.walk(base):
            for fn in fs:
                if not fn.endswith('.smali'):
                    continue
                p = os.path.join(dp, fn)
                with open(p, encoding='utf-8', errors='ignore') as f:
                    src = f.read()
                dst, n = stub_sdk(src)
                if dst != src:
                    with open(p, 'w', encoding='utf-8', newline='') as f:
                        f.write(dst)
                fc += 1
                mc += n
        print('  %-22s %4d 文件 / %5d 方法体已清空' % (d, fc, mc))
        total_files += fc
        total_methods += mc
    print('  合计 %d 文件 / %d 方法' % (total_files, total_methods))

    print('=== 2) 短路自有代码入口 ===')
    for rel, names in SHORT_METHODS.items():
        p = os.path.join(SMALI, *rel.split('/'))
        with open(p, encoding='utf-8', errors='ignore') as f:
            src = f.read()
        dst, hit = short_methods(src, names, timer=('SplashActivity' in rel))
        with open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(dst)
        print('  %-56s %s' % (os.path.basename(p), hit))

    print('=== 3) 清理清单 ===')
    p = os.path.join(ROOT, 'AndroidManifest.xml')
    with open(p, encoding='utf-8', errors='ignore') as f:
        src = f.read()
    dst, removed = strip_manifest(src)
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(dst)
    print('  删除 %d 个组件/权限' % len(removed))
    for r in removed:
        print('    -', r)

    print('=== 4) 删除广告与开发残留资源 ===')
    freed = 0
    for rel in DROP_PATHS:
        p = os.path.join(ROOT, *rel.split('/'))
        if os.path.isdir(p):
            size = sum(os.path.getsize(os.path.join(dp, fn))
                       for dp, _, fs in os.walk(p) for fn in fs)
            shutil.rmtree(p)
            freed += size
            print('  [目录] %-30s %.1f KB' % (rel, size / 1024))
        elif os.path.isfile(p):
            size = os.path.getsize(p)
            os.remove(p)
            freed += size
            print('  [文件] %-30s %.1f KB' % (rel, size / 1024))
    # 同步 apktool.yml 中已删除的 unknown/bin 条目
    y = os.path.join(ROOT, 'apktool.yml')
    if os.path.isfile(y):
        with open(y, encoding='utf-8', errors='ignore') as f:
            yl = f.readlines()
        yl = [l for l in yl if not re.match(r'^\s+bin/', l)]
        with open(y, 'w', encoding='utf-8', newline='') as f:
            f.writelines(yl)
    print('  共释放 %.2f MB（未压缩）' % (freed / 1048576))
    print('=== 修改完成 ===')


if __name__ == '__main__':
    main()
