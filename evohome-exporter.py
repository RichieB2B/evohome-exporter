#!/usr/bin/python3 -u

import sys
import time
import datetime as dt
from evohomeclient2 import EvohomeClient
from keys import username, password
import prometheus_client as prom

poll_interval = 60


class hashabledict(dict):
    def __hash__(self):
        return hash(tuple(sorted(self.items())))


def exceptKeyError(func, *args):
    try:
        return func(*args)
    except KeyError:
        pass


def loginEvohome(myclient):
    try:
        myclient._login()
    except Exception as e:
        print("{}: {}".format(type(e).__name__, str(e)), file=sys.stderr)
        return False
    return True


def _get_set_point(zone_schedule, day_of_week, spot_time):
    daily_schedules = {
        s["DayOfWeek"]: s["Switchpoints"] for s in zone_schedule["DailySchedules"]
    }
    if not daily_schedules:
        return None
    switch_points = {
        dt.time.fromisoformat(s["TimeOfDay"]): s["heatSetpoint"]
        for s in daily_schedules[day_of_week]
    }
    candidate_times = [k for k in switch_points.keys() if k <= spot_time]
    if len(candidate_times) == 0:
        # no time less than current time
        return None

    candidate_time = max(candidate_times)
    return switch_points[candidate_time]


def calculate_planned_temperature(zone_schedule):
    current_time = dt.datetime.now().time()
    day_of_week = dt.datetime.today().weekday()
    return _get_set_point(zone_schedule, day_of_week, current_time) or _get_set_point(
        zone_schedule, day_of_week - 1 if day_of_week > 0 else 6, dt.time.max
    ) or 0


schedules_updated = dt.datetime.min
schedules = {}


def get_schedules():
    global schedules_updated
    global schedules

    # this takes time, update once per hour
    if schedules_updated < dt.datetime.now() - dt.timedelta(hours=1):
        for zone in client._get_single_heating_system()._zones:
            try:
                schedules[zone.zoneId] = zone.schedule()
            except:
                schedules[zone.zoneId] = { "DailySchedules": [] }

        # schedules = {
        #     zone.zone_id: zone.schedule()
        #     for zone in client._get_single_heating_system()._zones
        # }
        schedules_updated = dt.datetime.now()


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
    zfault = prom.Gauge(
        "evohome_zone_fault",
        "Evohome zone has active fault(s)",
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
        ["id"],
    )
    tcsfault = prom.Gauge(
        "evohome_temperaturecontrolsystem_fault",
        "Evohome temperatureControlSystem has active fault(s)",
        ["id"],
    )
    tcsmode = prom.Enum(
        "evohome_temperaturecontrolsystem_mode",
        "Evohome temperatureControlSystem mode",
        ["id"],
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
    tcsalerts = set()
    zonealerts = dict()

    oldids = set()
    labels = {}
    lastup = False
    while True:
        temps = []
        newids = set()
        try:
            temps = list(client.temperatures())
            get_schedules()
            loggedin = True
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
            tcs = client._get_single_heating_system()
            sysmode = tcs.systemModeStatus
            tcsperm.labels(client.system_id).set(
                float(sysmode.get("isPermanent", True))
            )
            tcsmode.labels(client.system_id).state(sysmode.get("mode", "Auto"))
            if tcs.activeFaults:
                tcsfault.labels(client.system_id).set(1)
                for af in tcs.activeFaults:
                    afhd = hashabledict(af)
                    if afhd not in tcsalerts:
                        tcsalerts.add(afhd)
                        print(
                            "fault in temperatureControlSystem: {}".format(af),
                            file=sys.stderr,
                        )
            else:
                tcsfault.labels(client.system_id).set(0)
                tcsalerts = set()
            for d in temps:
                newids.add(d["id"])
                labels[d["id"]] = [d["name"], d["thermostat"], d["id"]]
                if d["temp"] is None:
                    zavail.labels(d["name"], d["thermostat"], d["id"]).set(0)
                    exceptKeyError(
                        eht.remove, d["name"], d["thermostat"], d["id"], "measured"
                    )
                else:
                    zavail.labels(d["name"], d["thermostat"], d["id"]).set(1)
                    eht.labels(d["name"], d["thermostat"], d["id"], "measured").set(
                        d["temp"]
                    )
                eht.labels(d["name"], d["thermostat"], d["id"], "setpoint").set(
                    d["setpoint"]
                )
                eht.labels(d["name"], d["thermostat"], d["id"], "planned").set(
                    calculate_planned_temperature(schedules[d["id"]])
                )
                zmode.labels(d["name"], d["thermostat"], d["id"]).state(
                    d.get("setpointmode", "FollowSchedule")
                )
                if d["id"] not in zonealerts.keys():
                    zonealerts[d["id"]] = set()
                if d.get("activefaults"):
                    zonefault = 1
                    for af in d["activefaults"]:
                        afhd = hashabledict(af)
                        if afhd not in zonealerts[d["id"]]:
                            zonealerts[d["id"]].add(afhd)
                            print(
                                "fault in zone {}: {}".format(d["name"], af),
                                file=sys.stderr,
                            )
                else:
                    zonefault = 0
                    zonealerts[d["id"]] = set()
                zfault.labels(d["name"], d["thermostat"], d["id"]).set(zonefault)
            lastup = True
        else:
            up.set(0)
            if lastup:
                exceptKeyError(tcsperm.remove, client.system_id)
                exceptKeyError(tcsfault.remove, client.system_id)
                exceptKeyError(tcsmode.remove, client.system_id)
            lastup = False

        for i in oldids:
            if i not in newids:
                exceptKeyError(eht.remove, *labels[i] + ["measured"])
                exceptKeyError(eht.remove, *labels[i] + ["setpoint"])
                exceptKeyError(eht.remove, *labels[i] + ["planned"])
                exceptKeyError(zavail.remove, *labels[i])
                exceptKeyError(zmode.remove, *labels[i])
                exceptKeyError(zfault.remove, *labels[i])
        oldids = newids

        time.sleep(poll_interval)
