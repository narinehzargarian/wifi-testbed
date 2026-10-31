"""Measures the network under each impairment and prints a table. Run as root on Linux."""
import time

from lab.topology import Lab, SERVER_IP, wait_for

SCENARIOS = [("clean", None), ("5% loss", "loss 5%"), ("20% loss", "loss 20%"), ("100 ms delay", "delay 100ms")]


def measure_roam(lab):
    lab.start_ap("ap1", channel=1)
    first_bssid = lab.wifi_status()["bssid"]
    start = time.monotonic()
    lab.stop_ap("ap0")
    wait_for(lambda: lab.wifi_status().get("wpa_state") == "COMPLETED"
             and lab.wifi_status().get("bssid") != first_bssid, timeout=30, interval=0.05)
    return time.monotonic() - start


def main():
    lab = Lab()
    try:
        lab.start()
        lab.go_online()
        print(f"{'scenario':<14}{'ping ms':>9}{'UDP loss %':>12}{'TCP Mbit/s':>12}")
        for name, netem in SCENARIOS:
            if netem:
                lab.impair(netem)
            _, rtt = lab.ping(SERVER_IP, count=10)
            udp_loss = lab.median_udp_loss()
            tcp = lab.iperf_tcp()
            print(f"{name:<14}{rtt or 0:>9.1f}{udp_loss:>12.1f}{tcp['bits_per_second'] / 1e6:>12.1f}")
        lab.run("wl-core", "tc qdisc del dev core-srv root")
        print(f"roam to second access point: {measure_roam(lab):.1f} s")
    finally:
        lab.stop_all()


if __name__ == "__main__":
    main()
