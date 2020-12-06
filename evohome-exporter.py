#!/usr/bin/python3

import sys
import datetime as dt
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


def _get_set_point(zone_schedule, day_of_week, spot_time):
    daily_schedules = {
        s["DayOfWeek"]: s["Switchpoints"] for s in zone_schedule["DailySchedules"]
    }
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
    )


schedules_updated = dt.datetime.min
schedules = {}


def get_schedules(metrics):
    global schedules_updated
    global schedules

    # this takes time, update once per hour
    if schedules_updated < dt.datetime.now() - dt.timedelta(hours=1):
        # schedules() is a factory, so convert it into a dict in order to get everything here and now
        schedules = dict(client.schedules())

    for schedule in schedules:
        planned_temperature = calculate_planned_temperature(schedule["schedule"])
        metrics["temp"].labels(schedule["name"], schedule["id"], "planned").set(
            planned_temperature
        )


def get_temperatures(metrics):
    for d in client.temperatures():
        metrics["temp"].labels(d["name"], d["id"], "measured").set(d["temp"])
        metrics["temp"].labels(d["name"], d["id"], "target").set(d["setpoint"])


if __name__ == "__main__":
    metrics = {}
    metrics["temp"] = prom.Gauge(
        "evohome_temperature_celcius",
        "Evohome measured temperature in degrees celsius",
        ["name", "id", "type"],
    )
    metrics["updated"] = prom.Gauge("evohome_updated", "Evohome client last updated")
    metrics["up"] = prom.Gauge("evohome_up", "Evohome client status")
    prom.start_http_server(8082)

    try:
        client = EvohomeClient(username, password, debug=True)
    except Exception as e:
        print(
            "ERROR: can't create EvohomeClient\n{}: {}".format(
                type(e).__name__, str(e)
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    while True:
        try:
            get_temperatures(metrics)
            get_schedules(metrics)
            metrics["updated"].set(time.time())
            metrics["up"].set(1)

        except Exception as e:
            print("{}: {}".format(type(e).__name__, str(e)), file=sys.stderr)
            metrics["up"].set(0)

        time.sleep(poll_interval)
