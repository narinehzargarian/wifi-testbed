# Test Plan

**Scope:** a small WPA2 Wi-Fi network with DHCP, DNS, and two routed hops to a server.

**Environment:** one Linux machine. Each device is a network namespace, radios come from the kernel's `mac80211_hwsim` driver, and the services are real: `hostapd`, `wpa_supplicant`, `dnsmasq`, and `iperf3`. Every test builds a fresh network.

**Out of scope:** radio conditions such as signal strength, interference, and real over-the-air throughput, since the air is simulated. Real routers, switches, and access points.

**Pass criteria:** all tests pass. On failure, daemon logs are saved as a CI artifact.

## 1. Wi-Fi

| ID | Objective | Steps | Expected result |
|---|---|---|---|
| WIFI-01 | Client joins with the correct passphrase | Start client with the correct passphrase | Reaches `COMPLETED`, with WPA2-PSK and CCMP |
| WIFI-02 | Wrong passphrase is rejected | Start client with a wrong passphrase | Never reaches `COMPLETED`, and no station on the AP |
| WIFI-03 | AP sees the client | Join, then dump stations on the AP | Client's MAC address is listed |
| WIFI-04 | Client rejoins after AP restart | Stop the AP, confirm the client drops, restart the AP | Client rejoins and traffic flows |
| WIFI-05 | Client roams to a second AP | Start a second AP on another channel, stop the first | Client joins the new BSSID, keeps its address, and traffic flows |

## 2. DHCP

| ID | Objective | Steps | Expected result |
|---|---|---|---|
| DHCP-01 | Lease settings are correct | Request a lease | Address in pool, /24 mask, correct gateway, DNS server, and 1 h lease |
| DHCP-02 | Lease is applied | Check the client's address and routes | Address and default route are present |
| DHCP-03 | Renewal is stable | Request again | Same address |
| DHCP-04 | No server | Stop the DHCP server, then request a lease | No lease and no address |

## 3. DNS

| ID | Objective | Steps | Expected result |
|---|---|---|---|
| DNS-01 | Known name resolves | Query the server's name | `NOERROR` with the right address |
| DNS-02 | Unknown name | Query a missing name | `NXDOMAIN` |
| DNS-03 | Tell DNS failure apart from network failure | Stop the DNS server, then query and ping by IP | Query times out, and ping has no loss |

## 4. Routing

| ID | Objective | Steps | Expected result |
|---|---|---|---|
| ROUTE-01 | Traffic takes the expected path | Traceroute to the server | AP, then router, then server |
| ROUTE-02 | Isolate a missing return route | Delete the router's route back to the client, then restore it | Server unreachable while AP stays reachable, then full recovery |
| ROUTE-03 | Forwarding disabled on the router | Turn forwarding off, then on | 100% loss, then full recovery |

## 5. Performance

| ID | Objective | Steps | Expected result |
|---|---|---|---|
| PERF-01 | Clean baseline | 5 Mbit/s UDP and a TCP run | Under 2% UDP loss, TCP above 1 Mbit/s |
| PERF-02 | Measured loss matches injected loss | Inject 20% loss on the router link | Measured UDP loss within 5 points of 20% |
| PERF-03 | Measured latency matches injected delay | Inject 100 ms delay | Round trip rises by 100 ms, within 25 ms |
| PERF-04 | TCP under loss | Inject 5% loss | TCP still delivers data, more slowly than the clean run |

## Checking the tests themselves

A test that can't fail proves nothing, so the suite was run against four deliberate breakages, and exactly the expected tests failed:

| Breakage | Tests that failed |
|---|---|
| AP set to the wrong cipher | WIFI-01 |
| DHCP hands out the wrong DNS server | DHCP-01 |
| DNS returns the wrong address | DNS-01 |
| Impairment silently not applied | PERF-02, PERF-03, PERF-04 |
