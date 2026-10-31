"""Builds a small Wi-Fi network on one Linux machine and tears it down again.

    sta0  ))) wifi (((  ap0/ap1 + br0  ---  core  ---  srv
    client              AP, DHCP, DNS       router     server
    10.10.0.100-150     10.10.0.1           10.20.0.2  10.30.0.10

Each box is a network namespace with its own interfaces and routes. The radios come from the
kernel's mac80211_hwsim driver, so hostapd and wpa_supplicant use the real 802.11 stack, and only
the air between the radios is simulated.
"""
import json
import os
import pathlib
import re
import shutil
import signal
import statistics
import subprocess
import tempfile
import time

STA, AP, CORE, SRV = "wl-sta", "wl-ap", "wl-core", "wl-srv"
NAMESPACES = [STA, AP, CORE, SRV]

SSID = "testbed"
PASSPHRASE = "correct-horse-battery"
AP_IP = "10.10.0.1"
CORE_IP = "10.20.0.2"
SERVER_IP = "10.30.0.10"
SERVER_NAME = "files.lab.test"

LEASE_SCRIPT = pathlib.Path(__file__).with_name("udhcpc-lease.sh")
UDP_PROBE = pathlib.Path(__file__).with_name("udp_probe.py")


def wait_for(condition, timeout, interval=0.25):
    """Polls until condition returns something truthy, and returns it. Returns None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(interval)
    return None


class Lab:
    def __init__(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="wifi-lab-"))
        self.procs = {}

    # ---- running commands ----

    def run(self, ns, command, check=True, timeout=30):
        full = f"ip netns exec {ns} {command}" if ns else command
        result = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=timeout)
        if check and result.returncode != 0:
            raise RuntimeError(f"{full}\n{result.stdout}\n{result.stderr}")
        return result

    def daemon(self, name, ns, command):
        log = open(self.dir / f"{name}.log", "w")
        self.procs[name] = subprocess.Popen(
            f"exec ip netns exec {ns} {command}", shell=True, stdout=log, stderr=subprocess.STDOUT
        )
        self.procs[name].log = log

    def stop(self, name):
        proc = self.procs.pop(name, None)
        if proc is None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.log.close()

    # ---- building the network ----

    def start(self):
        self._clean_host()
        self.run(None, "modprobe mac80211_hwsim radios=3")
        phys = wait_for(self._radios, timeout=5)
        if not phys:
            raise RuntimeError("mac80211_hwsim did not create 3 radios")
        for ns in NAMESPACES:
            self.run(None, f"ip netns add {ns}")
            self.run(ns, "ip link set lo up")
        self._add_radio(phys[0], STA, "sta0")
        self._add_radio(phys[1], AP, "ap0")
        self._add_radio(phys[2], AP, "ap1")
        self._wire()
        self.start_dhcp_dns()
        self.start_ap("ap0", channel=6)
        self.daemon("iperf3", SRV, "iperf3 --server")

    def stop_all(self):
        for name in list(self.procs):
            self.stop(name)
        self._clean_host()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _clean_host(self):
        for ns in NAMESPACES:
            self.run(None, f"ip netns del {ns}", check=False)
        # Removing the driver gives every test fresh radios.
        wait_for(lambda: self.run(None, "modprobe -r mac80211_hwsim", check=False).returncode == 0, timeout=5)

    @staticmethod
    def _radios():
        phys = sorted(os.listdir("/sys/class/ieee80211")) if os.path.isdir("/sys/class/ieee80211") else []
        return phys if len(phys) == 3 else None

    def _add_radio(self, phy, ns, name):
        self.run(None, f"iw phy {phy} set netns name {ns}")
        match = re.search(r"Interface (\S+)", self.run(ns, "iw dev").stdout)
        # A namespace can hold two radios, so pick the one on this phy.
        for iface in re.findall(r"Interface (\S+)", self.run(ns, "iw dev").stdout):
            if self.run(ns, f"cat /sys/class/net/{iface}/phy80211/name").stdout.strip() == phy:
                match = iface
        self.run(ns, f"ip link set {match} name {name}")

    def _veth(self, ns_a, name_a, ip_a, ns_b, name_b, ip_b):
        self.run(None, f"ip link add {name_a} netns {ns_a} type veth peer name {name_b} netns {ns_b}")
        for ns, name, ip in ((ns_a, name_a, ip_a), (ns_b, name_b, ip_b)):
            self.run(ns, f"ip addr add {ip} dev {name}")
            self.run(ns, f"ip link set {name} up")

    def _wire(self):
        self.run(AP, "ip link add br0 type bridge")
        self.run(AP, f"ip addr add {AP_IP}/24 dev br0")
        self.run(AP, "ip link set br0 up")
        self._veth(AP, "ap-up", "10.20.0.1/30", CORE, "core-ap", f"{CORE_IP}/30")
        self._veth(CORE, "core-srv", "10.30.0.1/24", SRV, "srv0", f"{SERVER_IP}/24")
        self.run(AP, f"ip route add default via {CORE_IP}")
        self.run(CORE, "ip route add 10.10.0.0/24 via 10.20.0.1")
        self.run(SRV, "ip route add default via 10.30.0.1")
        for ns in (AP, CORE):
            self.run(ns, "sysctl -qw net.ipv4.ip_forward=1")

    # ---- services ----

    def start_ap(self, iface, channel):
        conf = self.dir / f"hostapd-{iface}.conf"
        conf.write_text(
            f"interface={iface}\nbridge=br0\ndriver=nl80211\nssid={SSID}\nhw_mode=g\nchannel={channel}\n"
            f"wpa=2\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\nwpa_passphrase={PASSPHRASE}\n"
        )
        self.daemon(f"hostapd-{iface}", AP, f"hostapd {conf}")
        if not wait_for(lambda: "type AP" in self.run(AP, f"iw dev {iface} info").stdout
                        and "channel" in self.run(AP, f"iw dev {iface} info").stdout, timeout=10):
            raise RuntimeError(f"{iface} did not start")

    def stop_ap(self, iface):
        self.stop(f"hostapd-{iface}")

    def start_dhcp_dns(self):
        conf = self.dir / "dnsmasq.conf"
        conf.write_text(
            "interface=br0\nbind-interfaces\nno-resolv\nno-hosts\nuser=root\n"
            "dhcp-range=10.10.0.100,10.10.0.150,255.255.255.0,1h\n"
            f"dhcp-option=3,{AP_IP}\ndhcp-option=6,{AP_IP}\n"
            f"dhcp-leasefile={self.dir}/leases\n"
            f"local=/lab.test/\naddress=/{SERVER_NAME}/{SERVER_IP}\n"
        )
        self.daemon("dnsmasq", AP, f"dnsmasq --no-daemon --conf-file={conf}")
        time.sleep(0.2)

    def stop_dhcp_dns(self):
        self.stop("dnsmasq")

    # ---- the client ----

    def associate(self, passphrase=PASSPHRASE):
        conf = self.dir / "wpa.conf"
        conf.write_text(
            f"ctrl_interface={self.dir}/wpa\nap_scan=1\n"
            f'network={{\n ssid="{SSID}"\n psk="{passphrase}"\n key_mgmt=WPA-PSK\n}}\n'
        )
        self.run(STA, "ip link set sta0 up")
        self.daemon("wpa_supplicant", STA, f"wpa_supplicant -i sta0 -D nl80211 -c {conf}")

    def wifi_status(self):
        out = self.run(STA, f"wpa_cli -p {self.dir}/wpa -i sta0 status", check=False).stdout
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    def wait_associated(self, timeout=20):
        return wait_for(lambda: self.wifi_status().get("wpa_state") == "COMPLETED", timeout)

    def request_lease(self):
        """Runs a DHCP client. Returns the lease as a dict, or None if no server answered."""
        lease_file = self.dir / "lease.json"
        lease_file.unlink(missing_ok=True)
        self.run(
            STA,
            f"env LEASE_FILE={lease_file} busybox udhcpc -i sta0 -n -q -t 3 -T 1 -s {LEASE_SCRIPT}",
            check=False,
        )
        return json.loads(lease_file.read_text()) if lease_file.exists() else None

    def go_online(self):
        self.associate()
        if not self.wait_associated():
            raise RuntimeError("client did not associate")
        lease = wait_for(self.request_lease, timeout=15, interval=1)
        if not lease:
            raise RuntimeError("client did not get a DHCP lease")
        return lease

    # ---- measurements ----

    def ping(self, target, count=5):
        """Returns (loss percent, average round-trip ms or None)."""
        out = self.run(STA, f"ping -c {count} -i 0.2 -W 1 {target}", check=False).stdout
        loss = float(re.search(r"([\d.]+)% packet loss", out).group(1))
        rtt = re.search(r"= [\d.]+/([\d.]+)/", out)
        return loss, float(rtt.group(1)) if rtt else None

    def dig(self, name, server=AP_IP):
        return self.run(STA, f"dig @{server} {name} +time=1 +tries=1", check=False).stdout

    def trace(self, target):
        out = self.run(STA, f"traceroute -n -q 1 -w 1 {target}", check=False).stdout
        return re.findall(r"^\s*\d+\s+(\d+\.\d+\.\d+\.\d+)", out, flags=re.M)

    def udp_loss(self, packets_per_second=625, seconds=3):
        """Sends numbered 1000-byte packets (625 per second is 5 Mbit/s). Returns percent lost."""
        probe = f"python3 {UDP_PROBE}"
        receiver = subprocess.Popen(
            f"exec ip netns exec {SRV} {probe} recv", shell=True, stdout=subprocess.PIPE, text=True
        )
        time.sleep(0.3)
        sent = json.loads(
            self.run(STA, f"{probe} send --host {SERVER_IP} --pps {packets_per_second} --seconds {seconds}",
                     timeout=seconds + 10).stdout
        )["sent"]
        result = json.loads(receiver.communicate(timeout=seconds + 15)[0])
        print(f"udp probe: sent {sent}, received {result['received']}, longest gap {result['longest_gap']}")
        return 100.0 * (sent - result["received"]) / sent

    def median_udp_loss(self, runs=3):
        """One stall on the path can skew a single run, so take the median of several."""
        return statistics.median(self.udp_loss(seconds=2) for _ in range(runs))

    def iperf_tcp(self, seconds=4):
        out = self.run(STA, f"iperf3 -c {SERVER_IP} -t {seconds} --json", timeout=seconds + 20).stdout
        return json.loads(out)["end"]["sum_received"]

    def impair(self, netem):
        """Adds impairment on the router's link to the server, e.g. 'loss 20%' or 'delay 100ms'."""
        self.run(CORE, f"tc qdisc replace dev core-srv root netem {netem}")
