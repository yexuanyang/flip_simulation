# File Meanings

**gdb_command.txt** is the flip commands that will execute in gdb, it is generated by gdb.py

**gdb.py** use iomem.txt to generates gdb_command.txt and simulate the bits flip by running gdb.sh in a while loop.

**get_iomem.sh** run in qemu guest machine, it will generates iomem.txt

**iomem.txt** is the /proc/iomem in qemu guest machine. It is generated by the execution of **get_iomem.sh**

**gdb.txt** will be created after the execution of **gdb.py**. It is the gdb logging file.

**gdb.sh** will be execute by gdb.py using python3 `subprocess.run()`

# Usage

Simulate the random bits flip in qemu guest machine with gdb.

# Tutorial

## 1. Clone this repo in somewhere

Run `git clone https://github.com/yexuanyang/filp_simulation.git` or `git clone git@github.com:yexuanyang/filp_simulation.git`

Store the repo somewhere.

## 2. Make sure your QEMU and Kernel both support 9p shared filesystem

### 2.1. Download QEMU from the source (one optional way to support 9p)

Run these commands in bash to install QEMU from the source. QEMU source tar is obtained from its official website.

```bash
wget https://download.qemu.org/qemu-7.1.0.tar.xz –no-check-certificate
xz -d qemu-7.1.0.tar.xz
tar -xvf qemu-7.1.0.tar
cd qemu-7.1.0/
apt-get install -y gcc make  ninja-build libglib2.0-dev libmount-dev  meson git  libfdt-dev libpixman-1-dev zlib1g-dev libcap-ng-dev libattr1-dev
mkdir build
cd build
../configure --enable-kvm --enable-virtfs
make -j$(nproc)
make install
qemu-system-aarch64 --version
```

### 2.2. Make kernel with this config (one optional way to support 9p)

Enter `make LLVM=1 menuconfig` in the root directory of the kernel source. enter `/` to search these configs and open them.

```text
CONFIG_9P_FS=y
CONFIG_9P_FS_POSIX_ACL=y
CONFIG_9P_FS_SECURITY=y
CONFIG_NETWORK_FILESYSTEMS=y
CONFIG_NET_9P=y
CONFIG_NET_9P_DEBUG=y （Optional）
CONFIG_NET_9P_VIRTIO=y

For aarch64, also add:
CONFIG_PCI=y
CONFIG_PCI_HOST_COMMON=y
CONFIG_PCI_HOST_GENERIC=y
CONFIG_VIRTIO_PCI=y
CONFIG_VIRTIO_BLK=y
CONFIG_VIRTIO_NET=y
```

### 2.3. Mount 9p fs when qemu boot

Add `-virtfs local,path=/path/to/share,mount_tag=host0,security_model=passthrough,id=host0` or `-fsdev local,security_model=passthrough,id=fsdev0,path=<path-to-shared-dir-in-host> -device virtio-9p-pci,id=fs0,fsdev=fsdev0,mount_tag=hostshare`
after your qemu boot command to use 9p fs. I recommend the first way.

Then interacting with the qemu guest machine tty console, run `mount -t 9p -o trans=virtio,version=9p2000.L host0 /mnt/shared` to mount 9p fs in directory `/mnt/shared`.

You can also add a new line `host0 /mnt/shared 9p trans=virtio,version=9p2000.L 0 0` at the end of `/etc/fstab` to make the qemu mount 9p automatically.

### 2.4. Start gdb server when qemu boot

Add `-s -S` at the end of your boot command will start a gdb server at `localhost:1234` and wait for gdb to continue. Run `gdb -ex 'target remote:1234'` to attach the server. Enter `continue` will make the kernel boot.

## 3. Put the repo in the shared directory

Just `cp` or `mv` the code you clone at Step One in the Tutorial to the shared directory.

## 4. Run scripts in sequence

Firstly run `get_iomem.sh` in qemu guest machine to get `iomem.txt`

Secondly run `python3 gdb.py` in the host machine to simulate the bits flip. 

**Note**: Detach gdb server before `python3 gdb.py`, otherwise it will blocked because 1234 port is used.
