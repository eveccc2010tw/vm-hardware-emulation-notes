#!/usr/bin/env python3
"""把 Windows NTFS 分割區上 hiberfil.sys 的喚醒標頭（RSTR/HIBR）清零，讓 Windows 冷開機。

情境：Fast Startup 留下的休眠映像是在舊硬體（例如 virtio-scsi）上存的，換成 SATA/IDE 後
每次開機都嘗試喚醒 → 立即崩潰重開。清掉標頭後 Windows 會忽略該映像。

必須在 VM 關機時執行，會直接寫入區塊裝置。先建快照！
  qm stop <VMID> && qm snapshot <VMID> before-hiberfil-fix
  python3 clear-hiberfil-header.py /dev/zvol/<儲存集區>/vm-<VMID>-disk-0-part2

原理：從 NTFS 開機磁區的 $MFT 起點開始掃描 MFT 記錄，找到名為 hiberfil.sys 的
檔案，取出它 $DATA 的第一段 runlist（LCN），檢查該位置開頭 4 bytes 是 RSTR
（Fast Startup 待喚醒映像）還是 HIBR（休眠映像）；是的話把前 4096 bytes 清零。
Windows 讀不到有效標頭就忽略該映像，改走正常冷開機。
"""
import struct
import sys

dev = sys.argv[1]
f = open(dev, "r+b")
bs = f.read(512)
csz = struct.unpack_from("<H", bs, 11)[0] * bs[13]
mft = struct.unpack_from("<Q", bs, 48)[0]
r = struct.unpack_from("<b", bs, 64)[0]
rs = (1 << -r) if r < 0 else r * csz


def fx(x):
    x = bytearray(x)
    uo, uc = struct.unpack_from("<HH", x, 4)
    for i in range(1, uc):
        x[i * 512 - 2:i * 512] = x[uo + 2 * i:uo + 2 * i + 2]
    return bytes(x)


def runs(b):
    p = l = 0
    o = []
    while b[p]:
        h = b[p]
        p += 1
        a, c = h & 15, h >> 4
        n = int.from_bytes(b[p:p + a], "little")
        p += a
        d = int.from_bytes(b[p:p + c], "little", signed=True)
        p += c
        l += d
        o.append((l, n))
    return o


def attrs(x):
    o = struct.unpack_from("<H", x, 20)[0]
    while True:
        t, L = struct.unpack_from("<II", x, o)
        if t == 0xFFFFFFFF or L == 0:
            return
        yield t, x[o:o + L]
        o += L


f.seek(mft * csz)
r0 = fx(f.read(rs))
seg = []
cb = 0
for t, a in attrs(r0):
    if t == 0x80 and a[9] == 0:
        for l, n in runs(a[struct.unpack_from("<H", a, 32)[0]:]):
            seg.append((cb, cb + n * csz, l * csz))
            cb += n * csz
        break

for s, e, d in seg:
    f.seek(d)
    buf = f.read(e - s)
    for off in range(0, len(buf), rs):
        raw = buf[off:off + rs]
        if raw[:4] != b"FILE" or not struct.unpack_from("<H", raw, 22)[0] & 1:
            continue
        x = fx(raw)
        name = None
        for t, a in attrs(x):
            if t == 0x30 and a[8] == 0:
                vo = struct.unpack_from("<H", a, 20)[0]
                if struct.unpack_from("<Q", a, vo)[0] & 0xFFFFFFFFFFFF == 5:
                    nl = a[vo + 64]
                    name = a[vo + 66:vo + 66 + nl * 2].decode("utf-16le")
        if name and name.lower() == "hiberfil.sys":
            for t, a in attrs(x):
                if t == 0x80 and a[9] == 0 and a[8] == 1:
                    lcn = runs(a[struct.unpack_from("<H", a, 32)[0]:])[0][0]
                    f.seek(lcn * csz)
                    h = f.read(8)
                    print("before", h)
                    if h[:4] in (b"RSTR", b"HIBR"):
                        f.seek(lcn * csz)
                        f.write(b"\0" * 4096)
                        f.flush()
                        print("cleared")
                    else:
                        print("no resume header, nothing to do")
            sys.exit(0)
print("hiberfil.sys not found")
