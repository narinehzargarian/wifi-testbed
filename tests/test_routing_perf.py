"""Test plan sections 4 and 5: routing and performance under impairment."""
import pytest

from lab.topology import AP_IP, CORE, CORE_IP, SERVER_IP


def test_route_01_path_goes_through_both_routers(online):
    assert online.trace(SERVER_IP) == [AP_IP, CORE_IP, SERVER_IP]


def test_route_02_missing_return_route_breaks_traffic_and_restoring_it_recovers(online):
    assert online.ping(SERVER_IP)[0] == 0
    online.run(CORE, "ip route del 10.10.0.0/24")
    assert online.ping(SERVER_IP)[0] == 100
    # The first hop is still reachable, which narrows the fault to past the access point.
    assert online.ping(AP_IP)[0] == 0
    online.run(CORE, "ip route add 10.10.0.0/24 via 10.20.0.1")
    assert online.ping(SERVER_IP)[0] == 0


def test_route_03_forwarding_disabled_on_router_stops_traffic(online):
    online.run(CORE, "sysctl -qw net.ipv4.ip_forward=0")
    assert online.ping(SERVER_IP)[0] == 100
    online.run(CORE, "sysctl -qw net.ipv4.ip_forward=1")
    assert online.ping(SERVER_IP)[0] == 0


def test_perf_01_clean_network_baseline(online):
    udp = online.iperf_udp(mbits=5)
    assert udp["lost_percent"] < 2
    tcp = online.iperf_tcp()
    assert tcp["bits_per_second"] > 1_000_000


def test_perf_02_measured_udp_loss_matches_injected_loss(online):
    online.impair("loss 20%")
    assert online.iperf_udp(mbits=5)["lost_percent"] == pytest.approx(20, abs=5)


def test_perf_03_measured_latency_matches_injected_delay(online):
    baseline = online.ping(SERVER_IP)[1]
    online.impair("delay 100ms")
    delayed = online.ping(SERVER_IP)[1]
    assert delayed - baseline == pytest.approx(100, abs=25)


def test_perf_04_tcp_recovers_lost_packets_but_slows_down(online):
    clean = online.iperf_tcp()["bits_per_second"]
    online.impair("loss 5%")
    lossy = online.iperf_tcp()
    assert lossy["bits_per_second"] > 0
    assert lossy["bits_per_second"] < clean
