# wifi-testbed

An automated test lab for a small Wi-Fi network, written in Python with pytest. It builds the network on one Linux machine, tests it, breaks it on purpose, and measures how it behaves.

See the [test plan](docs/TEST_PLAN.md) for all 19 test cases.

**What's real and what's simulated:** the radios come from the Linux kernel's `mac80211_hwsim` driver, so the air between them is simulated. Everything else is real: the 802.11 and WPA2 stack, `hostapd`, `wpa_supplicant`, DHCP and DNS through `dnsmasq`, Linux routing, and TCP/UDP traffic. It has not been run on physical routers, switches, or access points.

## Network

```
 sta0  ))) Wi-Fi (((  ap0 / ap1 + bridge  ---  core  ---  srv
 client               access points,           router     server
 DHCP address         DHCP, DNS, gateway
 10.10.0.100-150      10.10.0.1                10.20.0.2  10.30.0.10
```

Each box is a Linux network namespace with its own interfaces and routes. Every test builds a fresh network, so one test's failure can't affect the next.

## What it tests

| Area | Examples |
|---|---|
| Wi-Fi | WPA2 join, wrong passphrase rejected, rejoin after an access point restart, roaming to a second access point |
| DHCP | Lease settings, renewal, no server available |
| DNS | Known name, unknown name, telling a DNS failure apart from a network failure |
| Routing | Expected path, missing return route, forwarding disabled on the router |
| Performance | Baseline, then measured loss and latency against injected impairment |

## Measurements

Ranges across five CI runs. Each run injects the impairment with `tc netem` on the router's link to the server.

| Scenario | Ping | UDP loss | TCP throughput |
|---|---|---|---|
| Clean | 0.1 ms | 0% | 327-961 Mbit/s |
| 5% loss | 0.1 ms | 5.0-5.7% | 25-122 Mbit/s |
| 20% loss | 0.1 ms | 19.4-21.2% | 0.3-1.6 Mbit/s |
| 100 ms delay | 100.1-100.2 ms | 0% | 59-85 Mbit/s |

Roaming to the second access point after the first one stops takes 3.9 s.

TCP drops far more than the loss rate because it treats loss as congestion and slows down. These throughput figures show relative behavior on a shared CI machine, not what real Wi-Fi hardware would reach.

## Running it

It needs Linux with root, because it creates namespaces and loads a kernel driver. It doesn't run on macOS.

```sh
sudo apt-get install hostapd wpasupplicant iw dnsmasq-base busybox-static iperf3 dnsutils traceroute python3-pytest
sudo python3 -m pytest tests -v
sudo python3 -m lab.measure
```

On some kernels, `mac80211_hwsim` is in the `linux-modules-extra` package. In CI, results are saved as artifacts, along with daemon logs from any failed test.

## Testing the tests

**Could the tests fail at all?** All 19 passed on the first run, which doesn't prove much. So I broke the network four ways: wrong cipher, wrong DNS server in the DHCP lease, wrong DNS answer, and impairment silently not applied. Exactly the six tests I predicted failed, and the other 13 passed.

**Were they reliable?** Repeated runs found two problems:

1. `iperf3` hung during a UDP test under 20% loss, in one of three runs. The measuring tool was failing, not the network. I replaced UDP measurement with a small probe (`lab/udp_probe.py`) that sends numbered packets and counts what arrives. It has no control connection to get stuck.
2. One of five runs then measured 44% loss with 20% injected, far outside normal variation. The cause isn't confirmed; a brief stall on the path or the CI machine is the likely explanation. Loss is now the median of three measurements, so a single stall can't skew it while a real fault still fails, and the probe reports its longest run of missing packets to help diagnose the next one. Five full runs (95 tests) then passed.

## Known limits

- Simulated radios have no signal strength, interference, or real airtime limits, so this can't test RF behavior.
- Roaming here happens only after an access point stops. The client's reconnect isn't a fast handoff (802.11r), and the 3.9 s mostly reflects scanning.
- Five clean runs raise confidence but don't prove the flakiness is gone, since the 44% result was rare and its cause isn't confirmed.
