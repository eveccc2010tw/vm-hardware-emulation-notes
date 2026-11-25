# 讓虛擬機在樣本眼中像一台實體機

同一支 Windows 程式在實體機和虛擬機上，可能走完全不同的執行路徑：讀到「自己在虛擬機裡」就休眠、延後、改走無害分支，或反過來癱瘓分析環境。這份筆記用一台實際在用的 Windows 10 逆向分析工作機（跑在 Proxmox VE 上）當例子，說明三件事：

1. 來賓作業系統到底從哪幾條路徑讀到「我是虛擬機」；
2. QEMU／Proxmox VE 的每一個參數分別關掉哪一條線索；
3. 為什麼改了硬體之後反而開不了機，以及怎麼驗證改了有沒有效。

> **適用範圍**：隔離的惡意程式分析實驗室。目的是讓樣本正常執行以觀察行為。
> 不是用來繞過遊戲防作弊、商業軟體授權或線上服務的裝置指紋機制。
> 這套設定只在沒有對外連線的實驗網段使用；分析樣本前確認快照與網路隔離。

---

## 1. 來賓是怎麼「看到」硬體的

作業系統不會「感覺」到自己被虛擬化，它只是一層一層讀介面，然後把讀到的東西兜起來。每一層都是可枚舉、可覆寫的：

| 探測路徑 | 來賓讀到什麼 | 由誰決定 |
| --- | --- | --- |
| `CPUID` 指令 | 葉 0x00000001 的 ECX bit 31（hypervisor present）、葉 0x40000000 起的 hypervisor vendor 字串 | KVM 是否設定該 bit；`-cpu ...,kvm=off` |
| `CPUID` 葉 0x00000001 EDX bit 5 | 是否支援 VMX（硬體虛擬化延伸） | 傳給來賓的 CPU 功能集合；`-vmx` |
| SMBIOS 表（`_SM_`／`_SM3_`，在 0xF0000 附近搜尋） | 系統廠商／型號／序號、主機板、機殼、BIOS 版本與日期 | QEMU 的 `-smbios`、PVE 的 `smbios1:` |
| ACPI 表頭 | RSDT／XSDT／DSDT／SSDT 的 OEM ID 與 OEM Table ID | `-machine x-oem-id=` |
| PCI 設定空間 | 每個裝置的 vendor:device ID（1af4 = Red Hat/virtio、1b36 = Red Hat QEMU） | 選了哪種虛擬裝置 |
| ATA `IDENTIFY DEVICE` | 硬碟型號、序號、是否 SSD、旋轉率 | `-set device.sata0.model=`、`serial=`、`ssd=` |
| 網卡 | MAC 前 3 bytes（OUI）、驅動程式與 PCI ID | `net0:` 的模型與 MAC |
| VGA option ROM 的 VBE 資訊 | OEM 字串（預設寫著 SeaBIOS） | 換掉 ROM，`-set device.vga.romfile=` |
| 裝置管理員／登錄檔／服務 | 曾安裝過哪些驅動（virtio、QEMU GA、Spice） | 來賓端歷史，設定檔關不掉 |

最後一列是重點：**前八列都可以用設定檔偽裝，第九列不行。** 很多人把 `.conf` 調得很漂亮，卻在 `HKLM\SYSTEM\CurrentControlSet\Enum\PCI\VEN_1AF4...` 留下 virtio 的裝置實例，一樣一眼看穿。

---

## 2. 對照：偽裝前後

Proxmox VE 預設給 Windows 的 VM 大致長這樣（沒改過的 `qm create` 結果）：

```text
CPU      : PVE 預設 CPU 模型（kvm64／x86-64-v2-AES 之類，CPUID 帶 hypervisor bit 與 "KVMKVMKVM"）
主機板   : QEMU / Standard PC (i440FX + PIIX, 1996)
BIOS     : SeaBIOS，日期 04/01/2014
機殼     : QEMU
ACPI     : OEM ID "BOCHS "、OEM Table ID "BXPC"
顯示卡   : Standard VGA（VBE OEM 字串 "SeaBIOS VBE(C) 2011"）
硬碟     : virtio-blk（PCI 1af4:1001），無型號、無序號
網卡     : virtio-net（PCI 1af4:1000）
其他     : virtio-balloon、QEMU guest agent 序列埠、PCI 熱插拔
```

改成下面這樣（完整設定見 `config/230.conf.example`）：

```text
CPU      : host 的型號，無 hypervisor bit，無 VMX
主機板   : Dell Inc. / 0K6WF6 A09
BIOS     : Dell 1.18.1（日期 11/15/2024）
機殼     : Dell / A09
ACPI     : OEM ID "ALASKA"
顯示卡   : stdvga + 改過 OEM 字串的 option ROM（Intel）
硬碟     : SATA AHCI，型號 KINGSTON SA400S37120G，有序號，ssd=1
網卡     : e1000e（Intel 82574L，PCI 8086:10d3）
其他     : 無 balloon、無 guest agent、無熱插拔
```

---

## 3. 逐層原理

### 3.1 CPUID hypervisor bit（最重要的一條）

KVM 預設會在 CPUID 葉 0x00000001 的 ECX bit 31 標記「我在 hypervisor 上執行」，並且在葉 0x40000000 回報廠商字串（KVM 是 `KVMKVMKVM`）。這兩個值是 virtio 廠商 ID 之外最常被檢查的線索，用 `coreinfo -v` 或 CPU-Z 一行就看得出來。

```text
cpu: host,hidden=1                        # PVE 語法：等於 -cpu host,kvm=off
args: ... -cpu host,...,kvm=off ...       # 命令列再寫一次，雙保險
```

`kvm=off` 的作用是叫 QEMU **不要**把 KVM 的 CPUID 特徵傳給來賓，於是 bit 31 為 0、0x40000000 葉不存在。副作用是來賓也看不到 `kvm_pv_eoi`、`kvm_pv_unhalt` 這些半虛擬化功能——那些本來就只對 Linux 來賓有意義，Windows 不受影響。

### 3.2 CPU 功能集合：把 VMX 拿掉

PVE2025 的 `kvm_intel nested=Y`，`-cpu host` 會把 VMX（硬體虛擬化延伸）一起傳給來賓。這有兩個後果：

1. **線索**：一台宣稱是 Dell R750 的機器有沒有 VMX，跟 BIOS 設定有關；VM 一律有，反而可疑。
2. **開不了機**：Windows 一看到 VMX，加上 `kvm=off` 讓它誤以為自己是實體機，就會啟動 `hvix64.exe` 跑 Hyper-V。在巢狀環境下它會卡死在 `winload` 讀到約 74 MB 的位置，8 顆 vCPU 全數停住。

解法是在命令列**再給一次** `-cpu`，把 vmx 相關功能拿掉：

```text
args: ... -cpu host,hv_ipi,...,kvm=off,...,-vmx-mbec,-vmx
```

QEMU 對同一個選項以**最後一個**為準，所以前面 PVE 產生的 `-cpu host,...` 會被這裡覆蓋，`hv_*`（Hyper-V 相容的 enlightenment 功能）要一併重寫，否則會跟著消失。

### 3.3 SMBIOS：廠商、型號、序號

SMBIOS 是韌體在記憶體裡放的一組結構化表格，Windows 透過 `GetSystemFirmwareTable('RSMB')` 讀，再映射成 WMI 的 `Win32_ComputerSystem`、`Win32_BIOS`、`Win32_BaseBoard`。QEMU 預設值是 `QEMU` / `Standard PC` / `SeaBIOS`，非常好認。

分兩處設定，因為 PVE 的 `smbios1:` 只產生 type 1：

```text
smbios1: uuid=...,manufacturer=...,product=...   # type 1：系統（PVE 原生欄位）
args: -smbios type=0,...  # BIOS 廠商、版本、日期
      -smbios type=2,...  # 主機板
      -smbios type=3,...  # 機殼
```

兩個實務細節：

- **不要**在 `args` 裡再給 `-smbios type=1`，會和 `smbios1:` 打架。PVE 會把 `smbios1:` 轉成自己的 `-smbios type=1`，兩份同時存在時誰蓋誰要看 QEMU 處理順序，不要依賴這種實作細節。
- `base64=1` 讓值用 base64 表示，避免逗號、空白與非 ASCII 破壞設定檔解析。`product=0K6WF6` 這種不含逗號的值可以直接寫，含逗號的就要編碼。

偽裝要一致：既然宣告是 PowerEdge R750，SMBIOS 的 `family`、`sku`、機殼、主機板型號都應該對得上，否則就是「一台自稱 R750 但主機板是 0K6WF6 的機器」這種矛盾組合。挑一個真實存在的機型，把它的公開型號字串整套照抄，是這個做法能自洽的唯一方式。

### 3.4 ACPI OEM ID

QEMU 的 ACPI 表（RSDT、XSDT、DSDT、SSDT）表頭有兩個 6 bytes 欄位：OEM ID 與 OEM Table ID，預設是 `BOCHS ` 與 `BXPC`。Windows 可以在 `HKLM\HARDWARE\ACPI\DSDT` 底下直接看到。

```text
args: -machine x-oem-id=ALASKA,x-oem-table-id=ALASKA
```

`ALASKA` 指的是 AMI 系韌體常見的 OEM ID，這個值取自原始設定。換成別的機型時，請用目標機 `acpidump` 實際讀到的值，不要憑印象填。

`x-oem-id`（上限 6 bytes）與 `x-oem-table-id`（上限 8 bytes）是 QEMU machine 的隱藏屬性，`x-` 前綴代表沒有正式文件保證，換 QEMU 版本要重測。實測（QEMU 8.2.2）：

```text
-machine pc                                     x-oem-id='BOCHS '  x-oem-table-id='BXPC    '   # 預設值
-machine x-oem-id=ALASKA,x-oem-table-id=ALASKA  x-oem-id='ALASKA'  x-oem-table-id='ALASKA'   # 本檔的寫法
```

另外這行**不必**指定 machine 型別：多個 `-machine` 是合併處理，後面的同名屬性覆蓋前面的，沒重複給的屬性會保留，所以它可以和 PVE 自己產生的那份並存。

### 3.5 儲存：SATA 而不是 virtio

virtio-blk／virtio-scsi 的 PCI vendor 是 `1af4`（Red Hat），而且需要自己裝驅動。來賓端會留下：

- 裝置實例 `HKLM\SYSTEM\CurrentControlSet\Enum\PCI\VEN_1AF4&DEV_1001...`
- `C:\Windows\INF\setupapi.dev.log` 裡的安裝紀錄
- 服務與驅動檔（`viostor.sys`、`vioscsi.sys`、`vioser.sys`）

改用 SATA（AHCI）後，來賓看到的是標準 AHCI 控制器，Windows 內建驅動直接支援，不會有第三方安裝紀錄。接著補上真實硬碟該有的欄位：

```text
sata0: local-lvm:vm-DISK,serial=...,size=120G,ssd=1
args: ... -set device.sata0.model=KINGSTON_SA400S37120G
```

- `serial=` 寫進 ATA `IDENTIFY DEVICE` 的序號欄位（word 10–19）。實體硬碟一定有，空的就露餡。
- `-set device.sata0.model=` 寫型號欄位（word 27–46）。預設是 `QEMU HARDDISK`。
- `ssd=1` 回報 non-rotating 並支援 TRIM，Windows 才會當 SSD（不重組、啟用 TRIM）；一般 `ssd=0` 會回報旋轉率 7200，和 SA400 這種入門 SATA SSD 對不上。

### 3.6 網卡：e1000e

virtio-net（`1af4:1000`）同樣是明顯線索。換成 e1000e（模擬 Intel 82574L，`8086:10d3`）：

```text
net0: e1000e=BC:24:11:00:00:01,bridge=vmbr0,firewall=1
```

有兩件事要記得：

- **OUI**：`BC:24:11` 是 Proxmox VE 註冊的 OUI。換掉廠商字串卻留著 PVE 的 MAC 前綴，等於自己招了。正式使用要挑目標機型網卡的 OUI。
- **MAC 唯一性**：實驗網段若同時有兩台同 MAC 的機器，會出現詭異的連線問題，也會被樣本當成異常環境。

e1000e 的效能比 virtio 差，但分析環境的取樣通常夠用；要抓大量封包時再評估。

### 3.7 顯示卡 option ROM 的 OEM 字串

`stdvga` 的 option ROM 是 QEMU 編譯出來的 SeaBIOS VGABIOS，Windows 透過 VBE（Int 10h `AX=4F00h`）取得的 `VbeInfoBlock` 裡，`OEMStringPtr` 指向的字串直接寫著 `SeaBIOS VBE(C) 2011`。這是在顯示卡內容頁或 HWiNFO 一看就中的地方。

[`scripts/patch-vgabios.py`](scripts/patch-vgabios.py) 的做法是把等長字串就地換掉，再重算 PCI option ROM 的 checksum（整份 image 位元組總和 mod 256 必須為 0）：

```text
SeaBIOS VBE(C) 2011   -> Intel(R) HD Graphic
SeaBIOS Developers    -> Intel Corporation
SeaBIOS VBE Adapter   -> Intel(R) HD Graphic
```

換完把 ROM 放到主機上，再用 `-set device.vga.romfile=` 指過去。必須等長，是因為 ROM 裡有指標指向這些字串，長度一變所有位移都錯。必須重算 checksum，是因為 BIOS 與 Windows 都會驗，沒過就整顆 ROM 被忽略——症狀是「明明換了 ROM，字串還是 SeaBIOS」，很容易誤判成腳本沒跑。

### 3.8 來賓端殘留：設定檔關不掉的部分

硬體偽裝只解決「裝置看起來像什麼」，解決不了「這個 Windows 曾經裝過什麼」。這台機器從範本 clone 過來，`clean-base` 時期裝過整套 virtio-win、QEMU guest agent、Spice agent，服務雖然沒在用，痕跡還在：

- 服務：`QEMU Guest Agent`、`spice-vdagent`、VirtIO balloon driver
- 驅動檔：`C:\Windows\System32\drivers\` 下的 `viostor.sys`、`vioscsi.sys`、`vioser.sys`
- PnP 實例：`HKLM\SYSTEM\CurrentControlSet\Enum\PCI\VEN_1AF4*`、`VEN_1B36*`
- 程式目錄：`C:\Program Files\Virtio-Win`、`C:\Program Files\SPICE Guest Tools`

要乾淨只有兩條路：從原始 Windows ISO 重裝，或用 `pnputil /delete-driver` 移除驅動、移除裝置與服務、清理 `setupapi` 紀錄。這是本方案**沒有做完**的部分，也是實際對抗強度高的樣本時，優先該補的洞。

設定檔能做的只有「不要新增」：

```text
agent: 0      # 不建立 virtio-serial 通道
balloon: 0    # 不建立 virtio-balloon（PCI 1af4:1002）
hotplug: 0    # 關閉 PCI 熱插拔控制器
```

---

## 4. 完整設定

| 檔案 | 內容 |
| --- | --- |
| [`config/230.conf.example`](config/230.conf.example) | 完整的 `/etc/pve/qemu-server/<VMID>.conf`，逐段有註解 |
| [`config/args.example`](config/args.example) | 單獨抽出 `args:` 那一行，方便對照 |
| [`scripts/patch-vgabios.py`](scripts/patch-vgabios.py) | 產生改過 OEM 字串的顯示卡 ROM |
| [`scripts/clear-hiberfil-header.py`](scripts/clear-hiberfil-header.py) | 換硬碟後清掉 Fast Startup 休眠映像（見第 6 節） |
| [`examples/pve-win10-resources.conf`](examples/pve-win10-resources.conf) | 只取資源欄位（CPU／記憶體／ostype）的精簡版 |

`args:` 那一行是本方案的核心，拆開看：

```text
-machine x-oem-id=ALASKA,x-oem-table-id=ALASKA          # ACPI OEM 欄位
-smbios type=0,vendor=Dell,version=1.18.1,...           # BIOS
-smbios type=2,manufacturer=Dell,product=0K6WF6,...     # 主機板
-smbios type=3,manufacturer=Dell,version=A09,...        # 機殼
-set device.sata0.model=KINGSTON_SA400S37120G           # 硬碟型號
-set device.vga.romfile=/root/stealth/vgabios-stdvga.bin # 顯示卡 ROM
-cpu host,hv_*...,kvm=off,...,-vmx-mbec,-vmx            # CPU 功能集合
```

---

## 5. 重建步驟

```sh
# 1. 建一台基本 VM（資源依原機：2 socket × 4 core、16 GiB）
qm create 9000 --name win10-lab --ostype win10 \
  --sockets 2 --cores 4 --memory 16384 --balloon 0 --numa 0

# 2. 產生顯示卡 ROM（在主機上，需要 QEMU 內建的 vgabios）
mkdir -p /root/stealth
python3 scripts/patch-vgabios.py /usr/share/kvm/vgabios-stdvga.bin /root/stealth/vgabios-stdvga.bin
python3 -c "print(sum(open('/root/stealth/vgabios-stdvga.bin','rb').read()) % 256)"   # 必須是 0

# 3. 套設定（或用編輯器改 /etc/pve/qemu-server/9000.conf）
qm set 9000 --sata0 local-lvm:64,serial=EXAMPLE000000001,ssd=1
qm set 9000 --net0 e1000e=BC:24:11:00:00:01,bridge=vmbr0,firewall=1
qm set 9000 --agent 0 --hotplug 0
qm set 9000 --smbios1 'uuid=...,manufacturer=...,base64=1'
qm set 9000 --args '<config/230.conf.example 裡那一行>'

# 4. 核對
qm config 9000
```

**不要設 `machine: q35`**，原因見第 6.2 節。預設的 i440fx 才和這套參數對得上（`x-oem-id`、PIIX/IDE 的 SATA 對應都是 i440fx 的路徑）。

---

## 6. 為什麼「看起來像實體機」反而開不了機

把上面全套套上去後，這台機器曾經完全開不了機。三個獨立原因，重建時一定會再遇到：

### 6.1 巢狀 Hyper-V 卡死

`hidden=1` + `kvm=off` 讓 Windows 相信自己是實體機，於是啟動 Hyper-V（`hvix64.exe`）。但底層 `kvm_intel nested=Y`，VMX 又被傳進去，結果 8 顆 vCPU 全部卡在 `winload` 讀到約 74 MB 的位置。

**解法**：`args` 末尾重下一次 `-cpu`，拿掉 `-vmx-mbec,-vmx`（見 3.2）。症狀是「開機畫面卡住、CPU 100%、沒有 BSOD」，很容易誤判成磁碟或記憶體問題。

### 6.2 q35 的 21 個 PCIe bridge 讓 QEMU 停住

`machine: q35` 會載入 `pve-q35-4.0.cfg`，裡面有 21 個 Red Hat `1b36:000c` PCIe 根埠。Windows 的 `pci.sys` 列舉時，QEMU 卡在 `synchronize_srcu_expedited` 約十分鐘；就算開起來，裝置管理員也會多出 21 個「Red Hat PCIe 根埠」——既慢又露餡。

**解法**：**不要設 `machine:`**，用預設 i440fx（和舊快照一致）。代價是開機時會有 `pc-i440fx-5.1` deprecated 警告，可以接受。

### 6.3 Fast Startup 的休眠映像

`C:\hiberfil.sys` 的標頭是 `RSTR`（Fast Startup 待喚醒）時，映像是**在舊硬體上（virtio-scsi）**存的。把系統碟從 `scsi0` 改成 `sata0` 之後，每次開機都嘗試喚醒 → 黑畫面立刻重開，連 BSOD 都來不及看到。

**解法**（VM 關機時執行，先建快照）：

```sh
qm stop 9000 && qm snapshot 9000 before-hiberfil-fix
python3 scripts/clear-hiberfil-header.py /dev/zvol/local-lvm/vm-9000-disk-0-part2
qm start 9000
```

清掉標頭後 Windows 會忽略該映像。長期解法是在來賓裡關掉 Fast Startup：`powercfg /h off`，或設 `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power\HiberbootEnabled = 0`。

---

## 7. 怎麼驗證

### 7.1 來賓內（PowerShell）

```powershell
Get-CimInstance Win32_ComputerSystem        | Select Manufacturer,Model
Get-CimInstance Win32_BIOS                  | Select Manufacturer,SMBIOSBIOSVersion,SerialNumber,ReleaseDate
Get-CimInstance Win32_BaseBoard             | Select Manufacturer,Product,SerialNumber
Get-CimInstance Win32_ComputerSystemProduct | Select Vendor,Name,UUID,IdentifyingNumber
Get-CimInstance Win32_DiskDrive             | Select Model,SerialNumber,InterfaceType,MediaType
Get-CimInstance Win32_NetworkAdapter        | Where-Object PhysicalAdapter | Select Name,MACAddress
Get-CimInstance Win32_PhysicalMemory        | Measure-Object        # 見下方說明
```

特別注意最後一行：實體 R750 會有十幾條 DIMM，虛擬機通常是 **0 筆**（`numa: 0`、沒有 memory device）。這是本方案目前最大的破口，也是最容易被寫得比較細的樣本抓到的點。

其餘要交叉核對的地方：

- `HKLM\HARDWARE\DESCRIPTION\System\BIOS`（韌體報告的原始字串）
- `HKLM\HARDWARE\ACPI\DSDT\*`（OEM ID 是否已變成 `ALASKA`）
- `HKLM\SYSTEM\CurrentControlSet\Enum\PCI\`（有沒有 `VEN_1AF4`、`VEN_1B36`）
- `C:\Windows\INF\setupapi.dev.log`（歷史安裝紀錄）
- `coreinfo -v`（Sysinternals，看有沒有 Hypervisor 字樣）
- 顯示卡內容 →「介面卡資訊」的 BIOS 字串

### 7.2 主機端

```sh
qm config 9000                       # 設定是否真的套上
qm monitor 9000                      # 進 monitor 後：
  info qtree                         # 實際的裝置樹與 model 字串
  info cpus                          # CPU 模型與功能
```

`qm config` 只反映設定檔，不代表來賓看到的一致；`info qtree` 才是 QEMU 真正建立的裝置。兩邊對不起來時，以 `info qtree` 為準。

要確認 ACPI 那兩個欄位真的套上，不必開機進 Windows，用 QMP 直接讀 machine 屬性就好：

```sh
qemu-system-x86_64 -machine x-oem-id=ALASKA,x-oem-table-id=ALASKA \
  -nodefaults -display none -S -qmp unix:/tmp/q.sock,server,nowait
# 另一端：QMP qom-get，path=/machine，property=x-oem-id / x-oem-table-id
```

### 7.3 對照測試

改了什麼就要有對照組，否則無法區分「樣本因為虛擬化而停止」和「樣本本來就不會動」：

1. 準備兩台同版本 Windows、同觀察時間的 VM，一台偽裝、一台不偽裝。
2. 每輪只改一個條件，從同一份乾淨快照開始。
3. 記錄程序樹、退出狀態、檔案與網路事件、時間戳。
4. 結果不同先重跑確認能重現，再往下拆。

---

## 8. 這套做法的極限

設定檔能改的都是「被問到時回什麼答案」，改不了「回答的物理特性」。以下是這套設定**沒有**解決、而且樣本確實會檢查的：

| 面向 | 為什麼藏不住 |
| --- | --- |
| 時間 | `RDTSC`／`RDTSCP` 的抖動與 TSC 頻率、`QueryPerformanceCounter` 的精度和實體機不同；VM 的時序抖動通常更大 |
| 晶片組拓撲 | 宣告 R750 卻只有 i440fx 的 PCI 拓撲：沒有 PCIe root complex、沒有 SMBus、沒有 IPMI/BMC 裝置，裝置數量少一截 |
| 記憶體 | 沒有 DIMM 資訊（`Win32_PhysicalMemory` 空）、沒有 ECC 相關欄位 |
| 韌體 | SeaBIOS 的 ROM 裡仍留著 `rel-1.17.0-...prebuilt.qemu.org` 之類的建置字串；BIOS 行為也不會因為改了 SMBIOS 就變成 AMI Aptio |
| 硬碟 | 沒有真正的 SMART 資料；SATA/e1000e 的效能特徵與實體不同 |
| 網路 | 延遲、MTU、驅動統計值都與實體網卡不同 |
| 周邊 | 沒有 Intel ME/AMT、沒有實體 USB 控制器、沒有真正的音效裝置 |
| 開機路徑 | 走 SeaBIOS（Legacy）+ i440fx，不是 UEFI Secure Boot，和 R750 出貨設定不符 |

換句話說：**這套設定可以讓只看 SMBIOS／CPUID／PCI ID 的樣本正常執行，但擋不住會量測時序或比對完整裝置樹的樣本。** 真正要對抗強度高的樣本，需要加上記憶體熱插拔偽裝、CPU 模型微調，以及從乾淨的實體機擷取完整 ACPI 表。

---

## 9. 去敏說明

這份文件由內部的原始備份整理而來。公開版拿掉了所有可識別或可直接連回原機的資料：

| 欄位 | 公開版處理 |
| --- | --- |
| SMBIOS 序號（type 1/2/3） | 換成 `EXAMPLE` |
| `smbios1` 的 `uuid` | 重新產生，非原值 |
| 硬碟序號 `sata0: serial=` | 換成 `EXAMPLE000000001` |
| 網卡 MAC | 換成範例值（保留 `BC:24:11` 前綴作為說明用） |
| 儲存名稱與 VM ID | 換成 `local-lvm` / `9000` |
| 顯示卡 ROM 路徑 | 換成 `/root/stealth/` |
| 內網位址、遠端協助 ID、帳號、快照名稱 | 全部移除 |

保留的是公開可查的部分：Dell PowerEdge R750 的型號字串、Dell BIOS 版本號、Kingston SA400 的型號、QEMU／Proxmox 的參數語法。這些是「偽裝要一致」所必需的目標值，不是任何一台特定機器的識別碼。

> 本文依 2026-11-14 擷取的現役設定整理。整理後**未重新開機、未重跑樣本**，第 6 節的三個開機問題與第 7 節的驗證項目為當時的實際處理紀錄；公開版沒有重現整套環境，因此行為未重新驗證。

---

## 參考資料

- [QEMU 系統模擬文件](https://www.qemu.org/docs/master/system/introduction.html)
- [QEMU 啟動選項（`-smbios`、`-cpu`）](https://www.qemu.org/docs/master/system/invocation.html)
- [Proxmox VE 虛擬機設定文件](https://pve.proxmox.com/pve-docs/chapter-qm.html)
- [Proxmox VE `qm` 指令參考](https://pve.proxmox.com/pve-docs/qm.1.html)
- [SeaBIOS 專案](https://www.seabios.org/)
- [MITRE ATT&CK T1497：Virtualization/Sandbox Evasion](https://attack.mitre.org/techniques/T1497/)
