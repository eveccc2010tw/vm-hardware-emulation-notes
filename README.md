# 虛擬機如何呈現硬體

同一個程式在實體機和虛擬機上，可能走不同的執行路徑。這份筆記說明來賓作業系統如何辨識硬體，以及為什麼分析可疑程式時，需要把測試環境和觀察結果一起記錄。

## QEMU、KVM 與 Proxmox VE 各自做什麼

在 Proxmox VE 上，QEMU 建立來賓所見的主機板、磁碟控制器、網卡等裝置。KVM 透過主機 Linux 核心與 CPU 的虛擬化功能，加速執行來賓的 CPU 指令。Proxmox VE 管理虛擬機的生命週期、磁碟及網路。從來賓的角度來看，這些裝置各自有可枚舉的介面，作業系統可以安裝對應的驅動程式。[QEMU 系統模擬文件](https://www.qemu.org/docs/master/system/introduction.html) · [Proxmox VE 虛擬機文件](https://pve.proxmox.com/pve-docs/chapter-qm.html)

來賓取得硬體資訊有好幾條路徑。CPU 指令可回報處理器功能，韌體表提供系統與主機板資料，裝置匯流排讓作業系統辨識控制器和其他周邊。虛擬機啟動時，這些介面由虛擬硬體模型、韌體和選用的裝置共同形成。裝置直通時，來賓可直接使用被分配的實體裝置，其餘裝置仍可由 QEMU 提供。[QEMU 系統模擬文件](https://www.qemu.org/docs/master/system/introduction.html) · [Proxmox VE PCI Passthrough 文件](https://pve.proxmox.com/pve-docs/pve-admin-guide.html#qm_pci_passthrough)

## 為什麼同一個程式會有不同表現

有些程式會讀取硬體、驅動程式或系統資訊，再決定是否啟用某段功能。有些惡意樣本也會根據環境決定是否延後或停止執行。另外，虛擬化的時序、Windows 版本、驅動程式與檔案權限，都可能造成相似的表面現象。單次執行沒有觀察到預期行為，只能描述當時的測試結果。[MITRE ATT&CK：Virtualization/Sandbox Evasion](https://attack.mitre.org/techniques/T1497/)

## 怎麼記錄比較結果

先用良性程式驗證乾淨虛擬機能正常開機，並確認程序、檔案與網路事件的記錄正常。在兩組隔離的測試環境中維持相同的作業系統版本與觀察時間，每輪只改一個條件，分別保存程序樹、退出狀態及可觀察的副作用。如果測試結果不同，先重跑確認能否重現，再檢查驅動、授權或相容性差異。

例如，同一支測試程式在兩組環境都能啟動，但其中一組讀取測試檔時失敗。可先比對程式的退出狀態、檔案權限與程序事件。這樣可以區分程式從未啟動、啟動後遇到環境差異，以及觀測工具漏記這三種情況。每輪結束後回到已知乾淨的快照，讓下一輪有相同起點。
