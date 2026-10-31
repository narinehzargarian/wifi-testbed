"""Test plan section 1: Wi-Fi association and roaming."""
import time

from lab.topology import AP, SERVER_IP, SSID, wait_for


def test_wifi_01_correct_passphrase_joins_with_wpa2(lab):
    lab.associate()
    assert lab.wait_associated()
    status = lab.wifi_status()
    assert status["ssid"] == SSID
    assert status["key_mgmt"] == "WPA2-PSK"
    assert status["pairwise_cipher"] == "CCMP"


def test_wifi_02_wrong_passphrase_is_rejected(lab):
    lab.associate(passphrase="wrong-passphrase")
    assert not lab.wait_associated(timeout=10)
    # The access point must not have a station left associated.
    assert "Station" not in lab.run(AP, "iw dev ap0 station dump").stdout


def test_wifi_03_client_appears_on_the_access_point(online):
    client_mac = online.wifi_status()["address"]
    assert client_mac in online.run(AP, "iw dev ap0 station dump").stdout


def test_wifi_04_client_rejoins_after_access_point_restart(online):
    online.stop_ap("ap0")
    assert wait_for(lambda: online.wifi_status().get("wpa_state") != "COMPLETED", timeout=10)
    online.start_ap("ap0", channel=6)
    assert online.wait_associated(timeout=30)
    assert wait_for(lambda: online.ping(SERVER_IP, count=2)[0] < 100, timeout=15)


def test_wifi_05_client_roams_to_second_access_point_and_keeps_its_address(online):
    online.start_ap("ap1", channel=1)
    first_bssid = online.wifi_status()["bssid"]
    online.stop_ap("ap0")
    assert wait_for(
        lambda: online.wifi_status().get("wpa_state") == "COMPLETED"
        and online.wifi_status().get("bssid") != first_bssid,
        timeout=30,
    )
    assert online.wifi_status()["ip_address"] == online.lease["ip"]
    time.sleep(1)  # The bridge relearns where the client is from its first frames.
    assert wait_for(lambda: online.ping(SERVER_IP, count=2)[0] < 100, timeout=15)
