#!/usr/bin/python3

import sys
import time
from evohomeclient2 import EvohomeClient
from keys import username, password
import prometheus_client as prom

poll_interval = 60


def loginEvohome(myclient):
    try:
        myclient._login()
    except Exception as e:
        print("{}: {}".format(type(e).__name__, str(e)), file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    eht = prom.Gauge(
        "evohome_temperature_celcius",
        "Evohome temperatuur in celsius",
        ["name", "thermostat", "id", "type"],
    )
    zavail = prom.Gauge(
        "evohome_zone_available",
        "Evohome zone availability",
        ["name", "thermostat", "id"],
    )
    zmode = prom.Enum(
        "evohome_zone_mode",
        "Evohome zone mode",
        ["name", "thermostat", "id"],
        states=["FollowSchedule", "TemporaryOverride", "PermanentOverride"],
    )
    tcsperm = prom.Gauge(
        "evohome_temperaturecontrolsystem_permanent",
        "Evohome temperatureControlSystem is in permanent state",
    )
    tcsmode = prom.Enum(
        "evohome_temperaturecontrolsystem_mode",
        "Evohome temperatureControlSystem mode",
        states=[
            "Auto",
            "AutoWithEco",
            "AutoWithReset",
            "Away",
            "DayOff",
            "HeatingOff",
            "Custom",
        ],
    )
    upd = prom.Gauge("evohome_updated", "Evohome client last updated")
    up = prom.Gauge("evohome_up", "Evohome client status")
    prom.start_http_server(8082)
    try:
        client = EvohomeClient(username, password)
    except Exception as e:
        print(
            "ERROR: can't create EvohomeClient\n{}: {}".format(
                type(e).__name__, str(e)
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    loggedin = True
    lastupdated = 0

    while True:
        temps = []
        try:
            temps = list(client.temperatures())
            updated = True
            lastupdated = time.time()
        except Exception as e:
            print("{}: {}".format(type(e).__name__, str(e)), file=sys.stderr)
            temps = []
            updated = False
            loggedin = loginEvohome(client)
            if loggedin:
                continue

        if loggedin and updated:
            up.set(1)
            upd.set(lastupdated)
            sysmode = client._get_single_heating_system().systemModeStatus
            tcsperm.set(float(sysmode.get("isPermanent", True)))
            tcsmode.state(sysmode.get("mode", "Auto"))
            for d in temps:
                if d["temp"] is not None:
                    temp = d["temp"]
                    available = 1
                else:
                    temp = 0
                    available = 0
                eht.labels(d["name"], d["thermostat"], d["id"], "measured").set(temp)
                eht.labels(d["name"], d["thermostat"], d["id"], "setpoint").set(
                    d["setpoint"]
                )
                zavail.labels(d["name"], d["thermostat"], d["id"]).set(available)
                zmode.labels(d["name"], d["thermostat"], d["id"]).state(
                    d.get("setpointmode", "FollowSchedule")
                )
        else:
            up.set(0)

        time.sleep(poll_interval)
