"""Test plan sections 2 and 3: DHCP and DNS."""
import ipaddress

from lab.topology import AP_IP, SERVER_IP, SERVER_NAME


def test_dhcp_01_lease_has_correct_network_settings(online):
    lease = online.lease
    assert ipaddress.ip_address("10.10.0.100") <= ipaddress.ip_address(lease["ip"]) <= ipaddress.ip_address("10.10.0.150")
    assert lease["mask"] == "24"
    assert lease["router"] == AP_IP
    assert lease["dns"] == AP_IP
    assert lease["server"] == AP_IP
    assert lease["lease"] == 3600


def test_dhcp_02_address_is_applied_to_the_interface(online):
    assert f"inet {online.lease['ip']}/24" in online.run("wl-sta", "ip -4 addr show sta0").stdout
    assert f"default via {AP_IP}" in online.run("wl-sta", "ip route").stdout


def test_dhcp_03_renewal_keeps_the_same_address(online):
    assert online.request_lease()["ip"] == online.lease["ip"]


def test_dhcp_04_no_server_means_no_address(lab):
    lab.stop_dhcp_dns()
    lab.associate()
    assert lab.wait_associated()
    assert lab.request_lease() is None
    assert "inet " not in lab.run("wl-sta", "ip -4 addr show sta0").stdout


def test_dns_01_resolves_known_name(online):
    answer = online.dig(SERVER_NAME)
    assert "status: NOERROR" in answer
    assert SERVER_IP in answer


def test_dns_02_unknown_name_returns_nxdomain(online):
    assert "status: NXDOMAIN" in online.dig("missing.lab.test")


def test_dns_03_dns_failure_does_not_break_ip_connectivity(online):
    # Tells a DNS problem apart from a network problem, a common customer report.
    online.stop_dhcp_dns()
    assert "connection timed out" in online.dig(SERVER_NAME) or "no servers could be reached" in online.dig(SERVER_NAME)
    loss, _ = online.ping(SERVER_IP)
    assert loss == 0
