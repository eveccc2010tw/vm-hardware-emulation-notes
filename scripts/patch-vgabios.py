#!/usr/bin/env python3
"""重建偽裝用的 stdvga option ROM：把 SeaBIOS VBE 的 OEM 字串換成 Intel 字樣。

背景
----
QEMU 的 `stdvga` 顯示卡不是真的顯示卡，它的 option ROM 是 QEMU 專案編譯出來的
SeaBIOS VGABIOS。Windows 列舉顯示卡時會呼叫 VBE（Int 10h AX=4F00h）取得
VbeInfoBlock，其中 OEMStringPtr 指向的字串就直接寫著 "SeaBIOS"。
這個字串是最容易被人手動檢查發現的線索之一。

作法
----
1. 讀入 QEMU 內建的 vgabios-stdvga.bin（Proxmox VE 在 /usr/share/kvm/）。
2. 用等長字串就地覆蓋：長度必須完全相同，否則所有指向該字串的位移都會壞掉，
   所以不足的部分補 \0。
3. 重算 option ROM 的 checksum：PCI option ROM 規定整份 image 的位元組總和
   mod 256 必須為 0，最後一個 byte 用來補足。BIOS 與 Windows 都會驗這個值，
   改了內容卻沒重算 checksum，機器會直接忽略這顆 ROM。

用法（在 Proxmox VE 主機上執行）
--------------------------------
  python3 patch-vgabios.py /usr/share/kvm/vgabios-stdvga.bin /root/stealth/vgabios-stdvga.bin
  # 確認 checksum
  python3 -c "print(sum(open('/root/stealth/vgabios-stdvga.bin','rb').read()) % 256)"

注意
----
- 換 QEMU 版本就要重跑：每個版本的 VGABIOS 內容與字串都不同，字串找不到時
  本腳本會直接失敗，不會產生半套檔案。
- 只換 OEM 字串不會讓它變成真的 Intel 內顯：解析度模式表、PCI ID、驅動程式
  仍與實體機不同。這一點在 README「這套做法的極限」一節有說明。
"""
import sys

REPL = [
    (b"SeaBIOS VBE(C) 2011\x00", b"Intel(R) HD Graphic\x00"),
    (b"SeaBIOS Developers\x00", b"Intel Corporation\x00\x00"),
    (b"SeaBIOS VBE Adapter\x00", b"Intel(R) HD Graphic\x00"),
]

if len(sys.argv) != 3:
    sys.exit(f"用法：{sys.argv[0]} <來源 vgabios-stdvga.bin> <輸出的 ROM>")

src, dst = sys.argv[1], sys.argv[2]
d = bytearray(open(src, "rb").read())

for old, new in REPL:
    assert len(old) == len(new), "等長替換是硬性條件"
    i = d.find(old)
    if i < 0:
        sys.exit(f"找不到字串 {old!r}（vgabios 版本可能不同，需重新比對）")
    d[i:i + len(old)] = new

# 重算 PCI option ROM checksum：總和 mod 256 == 0
d[-1] = 0
d[-1] = (-sum(d)) % 256
assert sum(d) % 256 == 0

open(dst, "wb").write(d)
print(f"ok {dst} {len(d)} bytes")
